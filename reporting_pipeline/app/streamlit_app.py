"""
Multi-page Streamlit application for the reporting pipeline.

Run from reporting_pipeline/:
    streamlit run app/streamlit_app.py
"""

import hashlib
import io
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import settings
from src import loaders, reconciliation as recon_engine, mappings, fte_prep
from src import exporters, transformations, report_generator
from src.transformations import clean_replicon, clean_servicenow
from src.exporters import df_to_excel_bytes, to_excel_bytes
from src.mappings import HAS_JELLYFISH, HAS_RAPIDFUZZ

_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_TS   = datetime.now().strftime("%Y%m%d_%H%M%S")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _save_upload(uploaded_file) -> Path:
    """Write a Streamlit UploadedFile to a named temp file and return its path."""
    suffix = Path(uploaded_file.name).suffix
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.write(uploaded_file.getvalue())
    tmp.flush()
    return Path(tmp.name)


def _save_uploads(uploaded_files) -> list[Path]:
    return [_save_upload(f) for f in uploaded_files]


# ---------------------------------------------------------------------------
# Page: Reconciliation
# ---------------------------------------------------------------------------

def page_reconciliation():
    with st.sidebar:
        st.header("Files")
        replicon_uploads = st.file_uploader(
            "Replicon CSV(s)", type=["csv"], accept_multiple_files=True,
            help="One or more monthly Replicon Diary Notes exports",
        )
        sn_upload = st.file_uploader(
            "ServiceNow Excel", type=["xlsx"],
            help="Full time-card export — all sheets combined automatically",
        )
        st.divider()
        st.header("Matching thresholds")
        auto_accept = st.slider("Auto-accept ≥", 0.50, 1.00, settings.AUTO_ACCEPT_THRESHOLD, 0.01)
        review_low  = st.slider("Review floor ≥", 0.30, 0.90, settings.REVIEW_LOW_THRESHOLD, 0.01)
        st.divider()
        st.caption(f"jellyfish: {'✓' if HAS_JELLYFISH else '✗'}  rapidfuzz: {'✓' if HAS_RAPIDFUZZ else '✗'}")

    st.title("📊 Timesheet Reconciliation")

    if not replicon_uploads or not sn_upload:
        st.info("Upload Replicon CSV(s) and the ServiceNow Excel in the sidebar to begin.", icon="👈")
        with st.expander("Pipeline overview"):
            st.markdown("""
| Step | What happens |
|---|---|
| 1 | Files loaded and data quality checked |
| 2 | Replicon users matched to ServiceNow users (exact → fuzzy) |
| 3 | **Review gate** — uncertain matches must be confirmed before proceeding |
| 4 | ServiceNow scoped to Replicon date window, matched users, matching task codes |
| 5 | Hours aggregated and reconciled at `date × user × task_code` grain |
| 6 | Outputs: detail, by_user, monthly sheets, exceptions, summary |
""")
        return

    _file_hash = hashlib.md5(
        b"".join(f.getvalue() for f in replicon_uploads) + sn_upload.getvalue()
    ).hexdigest()
    if st.session_state.get("_recon_hash") != _file_hash:
        st.session_state._recon_hash = _file_hash
        st.session_state.proceed_confirmed = False
        st.session_state._corrected_map_bytes = None

    @st.cache_data(show_spinner=False)
    def _load(file_tuple, sn_bytes):
        rep_raw = loaders.load_replicon_bytes(list(file_tuple))
        sn_raw  = loaders.load_timecard_bytes(sn_bytes)
        return rep_raw, sn_raw, clean_replicon(rep_raw), clean_servicenow(sn_raw)

    @st.cache_data(show_spinner=False)
    def _match(file_tuple, sn_bytes, approved_bytes, aa, rl):
        _, _, rep_c, sn_c = _load(file_tuple, sn_bytes)
        approved = pd.read_excel(io.BytesIO(approved_bytes)) if approved_bytes else None
        return mappings.match_users(rep_c, sn_c, approved, aa, rl)

    @st.cache_data(show_spinner=False)
    def _run(file_tuple, sn_bytes, mapping, aa, rl):
        rep_raw, sn_raw, _, _ = _load(file_tuple, sn_bytes)
        return recon_engine.run(rep_raw, sn_raw, mapping, aa, rl)

    file_tuple = tuple((f.name, f.getvalue()) for f in replicon_uploads)

    with st.spinner("Loading files…"):
        replicon_raw, sn_raw, replicon_c, sn_c = _load(file_tuple, sn_upload.getvalue())

    st.divider()
    _bad_rep = int(replicon_c["date"].isna().sum())
    _bad_sn  = int(sn_c["date"].isna().sum())
    st.subheader(f"{'✅' if (_bad_rep + _bad_sn) == 0 else '⚠️'} Step 1 — Data Loaded")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Replicon rows",    f"{len(replicon_c):,}")
    col2.metric("Replicon users",   str(replicon_c["username"].nunique()))
    col3.metric("Replicon hours",   f"{replicon_c['hours'].sum():.1f} h")
    col4.metric("SN rows loaded",   f"{len(sn_raw):,}")

    c5, c6, c7, c8 = st.columns(4)
    c5.metric("Date range",
              f"{replicon_c['date'].min().date()} → {replicon_c['date'].max().date()}" if not replicon_c.empty else "—")
    c6.metric("SN unique users",  str(sn_raw["User ID"].nunique() if "User ID" in sn_raw.columns else "—"))
    c7.metric("SN sheets",        str(sn_raw["_sheet"].nunique()))
    c8.metric("SN total hours",   f"{pd.to_numeric(sn_raw['Time worked'], errors='coerce').fillna(0).sum():,.1f} h" if "Time worked" in sn_raw.columns else "—")

    if _bad_rep:
        st.error(f"⛔ {_bad_rep} Replicon rows have unparseable dates — expected DD.MM.YYYY")
    if _bad_sn:
        st.error(f"⛔ {_bad_sn} ServiceNow rows have unparseable dates")

    st.divider()
    with st.spinner("Matching users…"):
        user_mapping = _match(
            file_tuple, sn_upload.getvalue(),
            st.session_state.get("_corrected_map_bytes"),
            auto_accept, review_low,
        )

    needs_review = user_mapping[user_mapping["review_required"]]
    st.subheader(f"{'✅' if needs_review.empty else '⚠️'} Step 2 — User Matching")

    ms1, ms2, ms3, ms4 = st.columns(4)
    ms1.metric("Total users",    str(len(user_mapping)))
    ms2.metric("Auto-accepted",  str(user_mapping["match_status"].eq("auto_accepted").sum()))
    ms3.metric("Needs review",   str(len(needs_review)),
               delta="action required" if not needs_review.empty else None,
               delta_color="inverse" if not needs_review.empty else "off")
    ms4.metric("No match",       str(user_mapping["match_status"].isin(["no_match","rejected"]).sum()))

    with st.expander("Full mapping table"):
        st.dataframe(
            user_mapping[["replicon_username","servicenow_user_id","servicenow_name",
                           "match_method","final_score","match_status","review_required"]],
            use_container_width=True, hide_index=True,
            column_config={"final_score": st.column_config.ProgressColumn("final_score", min_value=0, max_value=1, format="%.3f"),
                           "review_required": st.column_config.CheckboxColumn("review_required")},
        )

    if not needs_review.empty and not st.session_state.get("proceed_confirmed", False):
        st.error(f"🛑 **{len(needs_review)} user(s) require review** — reconciliation paused.", icon="🛑")
        with st.container(border=True):
            st.dataframe(needs_review[["replicon_username","servicenow_user_id","match_method","final_score","match_status"]],
                         use_container_width=True, hide_index=True)
            dl_col, up_col = st.columns(2)
            with dl_col:
                st.download_button("📥 Download mapping template",
                                   data=df_to_excel_bytes(user_mapping),
                                   file_name=f"user_mapping_review_{_TS}.xlsx", mime=_MIME,
                                   use_container_width=True)
            with up_col:
                corrected = st.file_uploader("📤 Upload corrected mapping", type=["xlsx"], key="corrected_mapping")
                if corrected:
                    new_val = corrected.getvalue()
                    if new_val != st.session_state.get("_corrected_map_bytes"):
                        st.session_state._corrected_map_bytes = new_val
                        st.rerun()
            if st.checkbox("I understand — proceed with uncertain matches and flag them in output",
                           key="proceed_confirmed"):
                st.rerun()
        return

    st.divider()
    st.subheader("⏳ Step 3 — Running Reconciliation…")
    prog = st.progress(0, text="Aggregating…")
    try:
        results = _run(file_tuple, sn_upload.getvalue(), user_mapping, auto_accept, review_low)
    except Exception as exc:
        st.error(f"Reconciliation failed: {exc}")
        return
    prog.progress(100)
    prog.empty()

    s = results["summary"].set_index("metric")["value"].to_dict()
    st.subheader("✅ Step 3 — Reconciliation Complete")

    r1, r2, r3, r4, r5, r6 = st.columns(6)
    r1.metric("Replicon Hours",  f"{float(s['total_replicon_hours_after_aggregation']):,.1f} h")
    r2.metric("ServiceNow Hours",f"{float(s['total_servicenow_hours_after_aggregation']):,.1f} h")
    r3.metric("Net Variance",    f"{float(s['net_variance']):+,.2f} h",
              delta_color="inverse" if float(s["net_variance"]) != 0 else "off")
    r4.metric("Users Matched",   f"{int(s['total_users_matched'])} / {int(s['total_users_matched'])+int(s['total_users_unmatched'])}")
    r5.metric("Records Compared",f"{int(s['total_records_compared']):,}")
    r6.metric("Discrepancies",   f"{int(s['total_discrepancies']):,}")
    st.caption(f"Period: **{s['replicon_window_start']}** → **{s['replicon_window_end']}**  |  Grain: `date × user × task_code`")

    months = list(results["recon_by_month"].keys())
    tabs = st.tabs(["📋 Summary","👥 By User"] + [f"📅 {m}" for m in months] + ["⚠️ Exceptions","🔗 User Mapping","🔍 Detail"])
    tab_sum, tab_user, *tab_months, tab_exc, tab_map, tab_det = tabs

    with tab_sum:
        st.dataframe(results["summary"], use_container_width=True, hide_index=True)

    with tab_user:
        st.dataframe(results["recon_by_user"], use_container_width=True, hide_index=True)

    for tab, month in zip(tab_months, months):
        with tab:
            st.dataframe(results["recon_by_month"][month], use_container_width=True, hide_index=True)

    with tab_exc:
        exc = results["exception_report"]
        if exc.empty:
            st.success("No exceptions found")
        else:
            types = exc["exception_type"].dropna().unique().tolist()
            sel = st.multiselect("Filter by type", types, default=types)
            flt = exc[exc["exception_type"].isin(sel)] if sel else exc
            st.caption(f"{len(flt):,} rows")
            st.dataframe(flt, use_container_width=True, hide_index=True)

    with tab_map:
        st.dataframe(results["user_mapping"], use_container_width=True, hide_index=True)

    with tab_det:
        uf, vf = st.columns([3, 1])
        with uf:
            ufilter = st.multiselect("Filter by user", sorted(results["recon_table"]["user_id"].dropna().unique()), key="det_user")
        with vf:
            var_only = st.checkbox("Variance rows only", key="det_var")
        det = results["recon_table"]
        if ufilter:   det = det[det["user_id"].isin(ufilter)]
        if var_only:  det = det[det["variance"] != 0]
        st.caption(f"{len(det):,} rows")
        st.dataframe(det, use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("📥 Downloads")
    d1, d2, d3, d4 = st.columns(4)
    with d1:
        st.download_button("Reconciliation (all sheets)", data=to_excel_bytes(results),
                           file_name=f"reconciliation_{_TS}.xlsx", mime=_MIME, use_container_width=True)
    with d2:
        st.download_button("Exception Report", data=df_to_excel_bytes(results["exception_report"]),
                           file_name=f"exception_report_{_TS}.xlsx", mime=_MIME, use_container_width=True)
    with d3:
        st.download_button("User Mapping", data=df_to_excel_bytes(results["user_mapping"]),
                           file_name=f"user_mapping_{_TS}.xlsx", mime=_MIME, use_container_width=True)
    with d4:
        st.download_button("Summary", data=df_to_excel_bytes(results["summary"]),
                           file_name=f"summary_{_TS}.xlsx", mime=_MIME, use_container_width=True)


# ---------------------------------------------------------------------------
# Page: FTE Data Prep
# ---------------------------------------------------------------------------

def page_fte():
    with st.sidebar:
        st.header("Files")
        tc_uploads = st.file_uploader(
            "Time-card file(s)", type=["xls", "xlsx"],
            accept_multiple_files=True,
            help="One or more ServiceNow time-card exports",
        )

    st.title("📈 FTE Data Prep (Power BI)")

    if not tc_uploads:
        st.info("Upload one or more time-card Excel files in the sidebar.", icon="👈")
        with st.expander("What this produces"):
            st.markdown("""
| Sheet | Contents |
|---|---|
| `tech_weekly_fte` | Weekly FTE by technology group (no GEN overhead) |
| `graph1_total_fte` | Total hours + implied FTE (incl. GEN) with 100–119 band |
| `graph2_task_fte` | Task hours + implied FTE (excl. GEN) |
| `weekly_breakdown` | Full weekly summary with all metrics |
| `category_weekly_pivot` | Hours by category × week |
| `tech_weekly_fte_by_spec` | Weekly FTE by tech group + specialisation |
""")
        return

    @st.cache_data(show_spinner=False)
    def _run_fte(file_tuple):
        tmp_paths = []
        try:
            for name, data in file_tuple:
                suffix = Path(name).suffix
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
                tmp.write(data)
                tmp.flush()
                tmp_paths.append(Path(tmp.name))

            df_raw = loaders.load_timecard_multi(tmp_paths)
            df_raw = df_raw.drop_duplicates(keep="last")
            is_oncall = df_raw["Rate type"].astype(str).str.contains("On-Call", case=False, na=False)
            df = df_raw[~is_oncall].copy()
            df["Time worked"] = pd.to_numeric(df["Time worked"], errors="coerce").fillna(0)
            df["is_gen"] = df["Task"].astype(str).str.startswith("GEN")
            return df, fte_prep.prepare_fte_data(
                df,
                hours_per_fte=settings.HOURS_PER_FTE,
                fte_band=settings.FTE_BAND,
                tech_map=settings.TECH_MAP,
                task_categories=settings.TASK_CATEGORIES,
            )
        finally:
            for p in tmp_paths:
                try: p.unlink()
                except: pass

    file_tuple = tuple((f.name, f.getvalue()) for f in tc_uploads)

    with st.spinner("Processing time-card data…"):
        try:
            df, fte_results = _run_fte(file_tuple)
        except Exception as exc:
            st.error(f"FTE processing failed: {exc}")
            return

    weekly = fte_results["weekly"]

    st.subheader("✅ FTE Summary")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Weeks",         str(len(weekly)))
    m2.metric("Date range",    f"{weekly['week_start'].min().date()} → {weekly['week_start'].max().date()}")
    m3.metric("Avg total FTE", f"{weekly['total_fte'].mean():.1f}")
    m4.metric("Avg task FTE",  f"{weekly['task_fte'].mean():.1f}")

    m5, m6, m7, m8 = st.columns(4)
    m5.metric("Total hours (all weeks)",   f"{weekly['total_hours'].sum():,.0f} h")
    m6.metric("Task hours (no GEN)",       f"{weekly['task_hours'].sum():,.0f} h")
    m7.metric("GEN overhead hours",        f"{weekly['gen_hours'].sum():,.0f} h")
    m8.metric("Weeks in FTE band 100–119", str(int(weekly["in_band"].sum())))

    st.divider()
    tab_weekly, tab_tech, tab_pivot = st.tabs(["📅 Weekly breakdown", "🏷️ By tech group", "📊 Category pivot"])

    with tab_weekly:
        st.dataframe(
            weekly[["week","total_hours","total_fte","task_hours","task_fte","gen_hours","gen_fte","gen_pct","in_band"]].round(2),
            use_container_width=True, hide_index=True,
        )

    with tab_tech:
        st.caption("No-GEN task hours by technology group per week")
        st.dataframe(fte_results["tech_weekly_no_gen"], use_container_width=True, hide_index=True)

    with tab_pivot:
        st.caption("Hours by category × week (Grand Total row included)")
        st.dataframe(fte_results["pivot"], use_container_width=True)

    st.divider()
    st.subheader("📥 Downloads")

    def _fte_to_bytes(res):
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as w:
            res["tech_weekly_no_gen"].to_excel(w, sheet_name="tech_weekly_fte", index=False)
            res["graph1"].to_excel(w, sheet_name="graph1_total_fte", index=False)
            res["graph2"].to_excel(w, sheet_name="graph2_task_fte", index=False)
            res["weekly"].to_excel(w, sheet_name="weekly_breakdown", index=False)
            res["pivot"].to_excel(w, sheet_name="category_weekly_pivot")
            res["tech_weekly_spec_no_gen"].to_excel(w, sheet_name="tech_weekly_fte_by_spec", index=False)
            res["tech_weekly"].to_excel(w, sheet_name="tech_weekly_fte_gen", index=False)
            res["tech_weekly_spec"].to_excel(w, sheet_name="tech_weekly_fte_by_spec_gen", index=False)
        return buf.getvalue()

    def _tc_to_bytes(d):
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as w:
            d.to_excel(w, sheet_name="with_gen", index=False)
            d[~d["is_gen"]].to_excel(w, sheet_name="without_gen", index=False)
        return buf.getvalue()

    d1, d2 = st.columns(2)
    with d1:
        st.download_button("Power BI FTE Workbook",
                           data=_fte_to_bytes(fte_results),
                           file_name=f"powerbi_fte_weekly_{_TS}.xlsx", mime=_MIME,
                           use_container_width=True)
    with d2:
        st.download_button("Raw Timecard Data (with/without GEN sheets)",
                           data=_tc_to_bytes(df),
                           file_name=f"timecard_data_{_TS}.xlsx", mime=_MIME,
                           use_container_width=True)


# ---------------------------------------------------------------------------
# Page: Weekly Attendance
# ---------------------------------------------------------------------------

def page_weekly_attendance():
    with st.sidebar:
        st.header("Files")
        tc_uploads = st.file_uploader(
            "Time-card file(s)", type=["xls", "xlsx"],
            accept_multiple_files=True,
        )
        res_upload = st.file_uploader(
            "Resources.xlsx", type=["xlsx"],
            help="Resource roster — must contain sheet 'Resource List 20250206'",
        )
        st.divider()
        st.header("Threshold")
        hours_threshold = st.number_input("Compliant if ≥ N hours/week", min_value=1, value=settings.HOURS_THRESHOLD_WEEKLY)

    st.title("👥 Weekly Attendance Analysis")

    if not tc_uploads or not res_upload:
        st.info("Upload time-card file(s) and Resources.xlsx in the sidebar.", icon="👈")
        with st.expander("Output sheets"):
            st.markdown("""
| Sheet | Contents |
|---|---|
| `full_roster` | All resources: status, hours, daily breakdown. Green = Compliant, Yellow = Incomplete, Red = Ghost |
| `ghost_resources` | Resources with 0 hours logged |
| `incomplete_loggers` | Resources with 0 < hours < threshold, sorted by shortfall |
| `orphan_tc_users` | Time-card users not found in the roster |
| `legend` | Column and colour guide |
""")
        return

    @st.cache_data(show_spinner=False)
    def _run_attendance(tc_tuple, res_bytes, threshold):
        tc_paths, res_path = [], None
        try:
            for name, data in tc_tuple:
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=Path(name).suffix)
                tmp.write(data); tmp.flush()
                tc_paths.append(Path(tmp.name))
            res_tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
            res_tmp.write(res_bytes); res_tmp.flush()
            res_path = Path(res_tmp.name)

            tc_raw  = loaders.load_timecard_multi(tc_paths)
            res_raw = loaders.load_resources(res_path, settings.RESOURCES_SHEET)
            tc, tc_oncall = transformations.clean_timecard_for_attendance(tc_raw)
            resources = transformations.clean_resources(res_raw, settings.UID_OVERRIDES)

            week = tc["week_start"].max()
            tc_w  = tc[tc["week_start"] == week]
            tc_oc = tc_oncall[tc_oncall["week_start"] == week] if "week_start" in tc_oncall.columns else tc_oncall[tc_oncall.get("Date", pd.Series()).apply(lambda d: (d - pd.to_timedelta(d.weekday(), unit="D")).normalize() if pd.notna(d) else pd.NaT) == week]

            res_matched = mappings.match_roster_to_timecard(resources, tc_w, settings.UID_OVERRIDES)
            roster, orphans, ghost, incomplete, full, day_cols = report_generator.build_weekly_attendance(
                tc_w, tc_oc, res_matched, week, threshold
            )
            return roster, orphans, ghost, incomplete, full, day_cols, week
        finally:
            for p in tc_paths:
                try: p.unlink()
                except: pass
            if res_path:
                try: res_path.unlink()
                except: pass

    tc_tuple = tuple((f.name, f.getvalue()) for f in tc_uploads)

    with st.spinner("Building attendance roster…"):
        try:
            roster, orphans, ghost, incomplete, full, day_cols, week = _run_attendance(
                tc_tuple, res_upload.getvalue(), hours_threshold
            )
        except Exception as exc:
            st.error(f"Attendance analysis failed: {exc}")
            return

    n = len(roster)
    compliant = int((roster["hours_logged"] >= hours_threshold).sum())

    st.subheader(f"✅ Week of {week.date()}")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total roster",             str(n))
    m2.metric(f"Compliant (≥ {hours_threshold} h)", f"{compliant}  ({compliant/n*100:.0f}%)")
    m3.metric("Incomplete",               f"{len(incomplete)}  ({len(incomplete)/n*100:.0f}%)")
    m4.metric("Ghost (0 h)",              f"{len(ghost)}  ({len(ghost)/n*100:.0f}%)")

    m5, m6 = st.columns(2)
    m5.metric("Orphan TC users (not in roster)", str(len(orphans)))
    m6.metric("Total hours logged",       f"{roster['hours_logged'].sum():,.1f} h")

    st.divider()
    tab_full, tab_ghost, tab_inc, tab_orphan = st.tabs(
        ["📋 Full roster", "👻 Ghost resources", "⚠️ Incomplete loggers", "🔍 Orphan TC users"]
    )

    with tab_full:
        st.dataframe(full, use_container_width=True, hide_index=True)

    with tab_ghost:
        if ghost.empty:
            st.success("No ghost resources this week")
        else:
            st.dataframe(ghost, use_container_width=True, hide_index=True)

    with tab_inc:
        if incomplete.empty:
            st.success("No incomplete loggers this week")
        else:
            st.dataframe(incomplete, use_container_width=True, hide_index=True)

    with tab_orphan:
        if orphans.empty:
            st.success("All TC users matched to roster")
        else:
            orphan_cols = [c for c in ["_uid","name_tc","hours_logged","hours_task","hours_gen","hours_other","hours_oncall","days_logged"] + day_cols if c in orphans.columns]
            st.dataframe(orphans[orphan_cols], use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("📥 Download")

    def _attendance_to_bytes(full_df, ghost_df, inc_df, orphans_df, day_cols_inner, week_inner, threshold_inner):
        buf = io.BytesIO()
        orphan_cols = [c for c in ["_uid","name_tc","hours_logged","hours_task","hours_gen","hours_other","hours_oncall","days_logged"] + day_cols_inner if c in orphans_df.columns]
        with pd.ExcelWriter(buf, engine="openpyxl") as w:
            full_df.to_excel(w, sheet_name="full_roster", index=False)
            ghost_df.to_excel(w, sheet_name="ghost_resources", index=False)
            inc_df.to_excel(w, sheet_name="incomplete_loggers", index=False)
            orphans_df[orphan_cols].to_excel(w, sheet_name="orphan_tc_users", index=False)
        return buf.getvalue()

    st.download_button(
        f"Download Attendance Report — week of {week.date()}",
        data=_attendance_to_bytes(full, ghost, incomplete, orphans, day_cols, week, hours_threshold),
        file_name=f"attendance_{week.date()}_{_TS}.xlsx",
        mime=_MIME, use_container_width=True,
    )


# ---------------------------------------------------------------------------
# Page: Monthly Attendance
# ---------------------------------------------------------------------------

def page_monthly_attendance():
    with st.sidebar:
        st.header("Files")
        tc_data_upload = st.file_uploader(
            "timecard_data.xlsx",
            type=["xlsx"],
            help="Output of the FTE Data Prep page (with_gen sheet)",
        )
        res_upload = st.file_uploader(
            "Resources.xlsx", type=["xlsx"],
            help="Resource roster",
        )
        st.divider()
        st.header("Period")
        month_start = st.date_input("From", value=pd.Timestamp("2026-06-01").date())
        month_end   = st.date_input("To",   value=pd.Timestamp("2026-07-05").date())
        month_label = st.text_input("Label (used in filenames)", value="Jun 2026")
        st.divider()
        st.header("Thresholds")
        week_threshold  = st.number_input("Weekly (h)", min_value=1, value=settings.HOURS_THRESHOLD_WEEKLY)
        month_threshold = st.number_input("Monthly (h)", min_value=1, value=settings.HOURS_THRESHOLD_MONTHLY)

    st.title("📅 Monthly Compliance Analysis")

    if not tc_data_upload or not res_upload:
        st.info("Upload timecard_data.xlsx (from FTE prep) and Resources.xlsx in the sidebar.", icon="👈")
        st.markdown("""
**Workflow:**
1. Run **FTE Data Prep** first and download `timecard_data.xlsx`
2. Upload that file here along with `Resources.xlsx`
3. Set the analysis period and thresholds
""")
        return

    @st.cache_data(show_spinner=False)
    def _run_monthly(tc_bytes, res_bytes, start_str, end_str, label, w_thresh, m_thresh):
        res_path = None
        try:
            month_start_ts = pd.Timestamp(start_str)
            month_end_ts   = pd.Timestamp(end_str)

            tc_raw = pd.read_excel(io.BytesIO(tc_bytes), sheet_name="with_gen")
            tc_raw["Date"] = pd.to_datetime(tc_raw["Date"], errors="coerce")
            tc_raw["week_start"] = (tc_raw["Date"] - pd.to_timedelta(tc_raw["Date"].dt.weekday, unit="D")).dt.normalize()
            tc_raw["Time worked"] = pd.to_numeric(tc_raw["Time worked"], errors="coerce").fillna(0)
            tc_raw = (
                tc_raw[(tc_raw["Date"] >= month_start_ts) & (tc_raw["Date"] <= month_end_ts)]
                .drop_duplicates(keep="last").reset_index(drop=True)
            )

            res_tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
            res_tmp.write(res_bytes); res_tmp.flush()
            res_path = Path(res_tmp.name)
            res_raw = loaders.load_resources(res_path, settings.RESOURCES_SHEET)

            tc, tc_oncall = transformations.clean_timecard_for_attendance(tc_raw)
            resources = transformations.clean_resources(res_raw, settings.UID_OVERRIDES)
            weeks = sorted(tc["week_start"].unique())
            res_matched = mappings.match_roster_to_timecard(resources, tc, settings.UID_OVERRIDES)

            roster, orphans, ghost, incomplete, full, wk_cols = report_generator.build_monthly_attendance(
                tc, tc_oncall, res_matched, weeks, m_thresh, w_thresh
            )

            week_rosters = {}
            for w in weeks:
                tc_w  = tc[(tc["week_start"] == w) & (tc["Date"] >= month_start_ts) & (tc["Date"] <= month_end_ts)]
                tc_oc = tc_oncall[(tc_oncall["week_start"] == w) & (tc_oncall["Date"] >= month_start_ts) & (tc_oncall["Date"] <= month_end_ts)] if "week_start" in tc_oncall.columns else pd.DataFrame(columns=tc_oncall.columns)
                if tc_w.empty: continue
                res_w = mappings.match_roster_to_timecard(resources, tc_w, settings.UID_OVERRIDES)
                week_dates = sorted(tc_w["Date"].dt.normalize().unique())
                day_cols_w = [d.strftime("%a %d/%m") for d in week_dates]
                roster_w, orphans_w, *_ = report_generator.build_weekly_attendance(
                    tc_w, tc_oc, res_w, w, w_thresh
                )
                week_rosters[w] = (roster_w, orphans_w, day_cols_w)

            return roster, orphans, ghost, incomplete, full, wk_cols, week_rosters, month_start_ts, month_end_ts
        finally:
            if res_path:
                try: res_path.unlink()
                except: pass

    with st.spinner("Building monthly compliance report…"):
        try:
            roster, orphans, ghost, incomplete, full, wk_cols, week_rosters, ms, me = _run_monthly(
                tc_data_upload.getvalue(), res_upload.getvalue(),
                str(month_start), str(month_end),
                month_label, week_threshold, month_threshold,
            )
        except Exception as exc:
            st.error(f"Monthly analysis failed: {exc}")
            return

    n = len(roster)
    compliant = int((roster["hours_logged"] >= month_threshold).sum())

    st.subheader(f"✅ {month_label}  ({ms.date()} → {me.date()})")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total roster",                  str(n))
    m2.metric(f"Compliant (≥ {month_threshold} h)", f"{compliant}  ({compliant/n*100:.0f}%)")
    m3.metric("Incomplete",                    f"{len(incomplete)}  ({len(incomplete)/n*100:.0f}%)")
    m4.metric("Ghost (0 h)",                   f"{len(ghost)}  ({len(ghost)/n*100:.0f}%)")

    m5, m6, m7 = st.columns(3)
    m5.metric("Orphan TC users",       str(len(orphans)))
    m6.metric("Total hours logged",    f"{roster['hours_logged'].sum():,.1f} h")
    m7.metric("Weeks analysed",        str(len(week_rosters)))

    st.divider()
    tab_full, tab_ghost, tab_inc, tab_weeks, tab_orphan = st.tabs(
        ["📋 Monthly roster", "👻 Ghosts", "⚠️ Incomplete", f"📅 Per week ({len(week_rosters)})", "🔍 Orphans"]
    )

    with tab_full:
        st.dataframe(full, use_container_width=True, hide_index=True)

    with tab_ghost:
        if ghost.empty: st.success("No ghosts for this period")
        else: st.dataframe(ghost, use_container_width=True, hide_index=True)

    with tab_inc:
        if incomplete.empty: st.success("No incomplete loggers for this period")
        else: st.dataframe(incomplete, use_container_width=True, hide_index=True)

    with tab_weeks:
        week_keys = sorted(week_rosters.keys())
        if week_keys:
            sel_week = st.selectbox("Select week", [str(w.date()) for w in week_keys])
            w_ts = next(w for w in week_keys if str(w.date()) == sel_week)
            roster_w, orphans_w, _ = week_rosters[w_ts]
            w_n = len(roster_w)
            w_comp = int((roster_w["hours_logged"] >= week_threshold).sum())
            wc1, wc2, wc3 = st.columns(3)
            wc1.metric("Compliant", f"{w_comp} / {w_n}")
            wc2.metric("Incomplete", str(int((roster_w["hours_logged"] > 0) & (roster_w["hours_logged"] < week_threshold)).sum() if w_n > 0 else 0))
            wc3.metric("Ghost", str(int((roster_w["hours_logged"] == 0).sum())))
            st.dataframe(roster_w, use_container_width=True, hide_index=True)

    with tab_orphan:
        if orphans.empty: st.success("All TC users matched to roster")
        else: st.dataframe(orphans, use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("📥 Download")

    def _monthly_to_bytes(full_df, ghost_df, inc_df, orphans_df, wk_cols_inner, week_ros, m_thresh_inner, w_thresh_inner):
        buf = io.BytesIO()
        orphan_base = ["_uid","name_tc","hours_logged","hours_task","hours_gen","hours_other","hours_oncall","days_logged"]
        orphan_exp  = [c for c in orphan_base if c in orphans_df.columns]
        with pd.ExcelWriter(buf, engine="openpyxl") as w:
            full_df.to_excel(w, sheet_name="june_full_roster", index=False)
            ghost_df.to_excel(w, sheet_name="ghost_june", index=False)
            inc_df.to_excel(w, sheet_name="incomplete_june", index=False)
            orphans_df[orphan_exp].to_excel(w, sheet_name="orphans_june", index=False)
            from src.report_generator import _build_full_roster
            for wk, (r_w, _, dc_w) in sorted(week_ros.items()):
                full_w = _build_full_roster(r_w, w_thresh_inner, dc_w)
                full_w.to_excel(w, sheet_name=f"week_{wk.date()}", index=False)
        return buf.getvalue()

    label_safe = month_label.replace(" ", "_").replace("/", "-")
    st.download_button(
        f"Download Compliance Report — {month_label}",
        data=_monthly_to_bytes(full, ghost, incomplete, orphans, wk_cols, week_rosters, month_threshold, week_threshold),
        file_name=f"compliance_{label_safe}_{_TS}.xlsx",
        mime=_MIME, use_container_width=True,
    )


# ---------------------------------------------------------------------------
# App entry point
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Reporting Pipeline",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

with st.sidebar:
    st.title("📊 Reporting Pipeline")
    st.divider()
    page = st.radio(
        "Select pipeline",
        ["Reconciliation", "FTE Data Prep", "Weekly Attendance", "Monthly Attendance"],
        label_visibility="collapsed",
    )
    st.divider()

if page == "Reconciliation":
    page_reconciliation()
elif page == "FTE Data Prep":
    page_fte()
elif page == "Weekly Attendance":
    page_weekly_attendance()
elif page == "Monthly Attendance":
    page_monthly_attendance()
