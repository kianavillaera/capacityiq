"""Staged reconciliation pipeline with review gate.

Run:  streamlit run app.py
"""

import hashlib
import io
from datetime import datetime

import pandas as pd
import streamlit as st

import reconciliation as rec

st.set_page_config(
    page_title="Timesheet Reconciliation",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_TS = datetime.now().strftime("%Y%m%d_%H%M%S")


def _excel_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    return buf.getvalue()


with st.sidebar:
    st.title("📊 Reconciliation")
    st.divider()

    st.markdown("**Files**")
    replicon_uploads = st.file_uploader(
        "Replicon CSV(s)",
        type=["csv"],
        accept_multiple_files=True,
        help="One or more monthly Replicon extracts",
    )
    sn_upload = st.file_uploader(
        "ServiceNow Excel",
        type=["xlsx"],
        help="Full time card export — all sheets combined automatically",
    )

    st.divider()
    st.markdown("**Matching Thresholds**")
    auto_accept = st.slider(
        "Auto-accept ≥",
        0.50,
        1.00,
        0.80,
        0.01,
        help="Fuzzy score at which a match is accepted without review",
    )
    review_low = st.slider(
        "Review floor ≥",
        0.30,
        0.90,
        0.70,
        0.01,
        help="Scores between this and auto-accept need review",
    )
    st.divider()
    st.caption(
        f"jellyfish: {'✓' if rec.HAS_JELLYFISH else '✗'}  "
        f"rapidfuzz: {'✓' if rec.HAS_RAPIDFUZZ else '✗'}"
    )

if not replicon_uploads or not sn_upload:
    st.title("📊 Timesheet Reconciliation")
    st.info("Upload files in the sidebar to start.", icon="👈")
    with st.expander("Pipeline overview"):
        st.markdown("""
| Step | What happens |
|------|-------------|
| 1 | Raw files loaded and data quality checked |
| 2 | Replicon users matched to ServiceNow users (exact → fuzzy) |
| 3 | **Review gate** — uncertain matches shown and must be confirmed before proceeding |
| 4 | ServiceNow scoped to Replicon date window, matched users, and matched task codes |
| 5 | Hours aggregated and reconciled at `date × user × task_code` grain |
| 6 | Outputs: detail, by_user, monthly sheets, exceptions, summary |

**To fix a wrong match:** download the mapping template → correct `servicenow_user_id`
and set `match_status = auto_accepted` → re-upload in Step 2.
        """)
    st.stop()

_file_hash = hashlib.md5(
    b"".join(f.getvalue() for f in replicon_uploads) + sn_upload.getvalue()
).hexdigest()

if st.session_state.get("_file_hash") != _file_hash:
    st.session_state._file_hash = _file_hash
    st.session_state.proceed_confirmed = False
    st.session_state._corrected_map_bytes = None


@st.cache_data(show_spinner=False)
def _load_and_clean(file_data_tuple: tuple, sn_bytes: bytes) -> tuple:
    rep_frames = []
    for name, b in file_data_tuple:
        df = pd.read_csv(io.BytesIO(b), dtype=str)
        df["_source_file"] = name
        rep_frames.append(df)
    replicon_raw = pd.concat(rep_frames, ignore_index=True)

    sn_frames = []
    with pd.ExcelFile(io.BytesIO(sn_bytes)) as xl:
        for sheet in xl.sheet_names:
            df = xl.parse(sheet)
            df["_sheet"] = sheet
            sn_frames.append(df)
    sn_raw = pd.concat(sn_frames, ignore_index=True)

    return (
        replicon_raw,
        sn_raw,
        rec.clean_replicon(replicon_raw),
        rec.clean_servicenow(sn_raw),
    )


@st.cache_data(show_spinner=False)
def _run_matching(file_data_tuple: tuple, sn_bytes: bytes, approved_bytes: bytes | None, aa: float, rl: float) -> pd.DataFrame:
    _, _, replicon_clean, sn_clean = _load_and_clean(file_data_tuple, sn_bytes)
    approved = pd.read_excel(io.BytesIO(approved_bytes)) if approved_bytes else None
    return rec.match_users(replicon_clean, sn_clean, approved, aa, rl)


@st.cache_data(show_spinner=False)
def _run_full(file_data_tuple: tuple, sn_bytes: bytes, user_mapping: pd.DataFrame, aa: float, rl: float) -> dict:
    replicon_raw, sn_raw, _, _ = _load_and_clean(file_data_tuple, sn_bytes)
    return rec.run(replicon_raw, sn_raw, user_mapping, aa, rl)


file_data_tuple = tuple((f.name, f.getvalue()) for f in replicon_uploads)

with st.spinner("Loading files…"):
    replicon_raw, sn_raw, replicon_clean, sn_clean = _load_and_clean(
        file_data_tuple, sn_upload.getvalue()
    )

st.title("📊 Timesheet Reconciliation")
st.divider()

_bad_rep = int(replicon_clean["date"].isna().sum())
_bad_sn = int(sn_clean["date"].isna().sum())
_s1_icon = "✅" if (_bad_rep + _bad_sn) == 0 else "⚠️"

st.subheader(f"{_s1_icon} Step 1 — Data Loaded")
with st.expander("🟦 Replicon — Data Profile", expanded=True):
    _r_dupes = int(
        replicon_clean.duplicated(subset=["date", "username", "task_code"]).sum()
    )
    _r_null_hours = int(
        replicon_raw["Hours"].isna().sum() if "Hours" in replicon_raw.columns else 0
    )
    _r_null_tc = int(replicon_clean["task_code"].isna().sum())
    _r_null_emp = int(replicon_clean["employee_id"].isna().sum())
    _r_zero_h_users = replicon_clean[replicon_clean["hours"] == 0]["username"].nunique()

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total rows", f"{len(replicon_clean):,}")
    m2.metric("Unique users", str(replicon_clean["username"].nunique()))
    m3.metric("Unique task codes", str(replicon_clean["task_code"].nunique()))
    m4.metric("Total hours", f"{replicon_clean['hours'].sum():.1f} h")

    st.markdown("")
    m5, m6, m7, m8 = st.columns(4)
    m5.metric(
        "Date range",
        f"{replicon_clean['date'].min().date()}",
        delta=f"→ {replicon_clean['date'].max().date()}",
        delta_color="off",
    )
    m6.metric(
        "Rows with 0 h",
        f"{int((replicon_clean['hours'] == 0).sum()):,}",
        help="Blank hours in source treated as 0 (business rule)",
    )
    m7.metric(
        "Duplicate rows",
        str(_r_dupes),
        delta="check needed" if _r_dupes > 0 else "none",
        delta_color="inverse" if _r_dupes > 0 else "off",
    )
    m8.metric(
        "Users with only 0 h",
        str(_r_zero_h_users),
        help="Users present in extract but all hours are zero",
    )

    st.markdown("")
    st.markdown("**Column null counts**")
    _rep_nulls = pd.DataFrame(
        [
            ("date", _bad_rep, "❌ fix date format (DD.MM.YYYY)" if _bad_rep else "✅"),
            ("username", int(replicon_clean["username"].isna().sum()), "✅"),
            ("employee_id", _r_null_emp, "⚠️ missing" if _r_null_emp else "✅"),
            (
                "task_code",
                _r_null_tc,
                "❌ required for reconciliation" if _r_null_tc else "✅",
            ),
            ("hours", _r_null_hours, "→ treated as 0" if _r_null_hours else "✅"),
        ],
        columns=["Column", "Nulls", "Status"],
    )
    st.dataframe(_rep_nulls, use_container_width=True, hide_index=True)

    st.markdown("**Hours by user** (top 20)")
    _rep_h_user = (
        replicon_clean.groupby("username")["hours"]
        .sum()
        .sort_values(ascending=False)
        .head(20)
        .reset_index()
        .rename(columns={"username": "User", "hours": "Hours"})
    )
    _rep_h_user["Hours"] = _rep_h_user["Hours"].round(2)
    st.dataframe(_rep_h_user, use_container_width=True, hide_index=True)

    if _bad_rep:
        st.error(f"⛔ {_bad_rep} rows have unparseable dates — expected DD.MM.YYYY")
    if _r_dupes > 0:
        st.warning(
            f"⚠️ {_r_dupes} duplicate (date, user, task_code) rows — hours will be summed during aggregation"
        )
    if _r_null_tc > 0:
        st.error(f"⛔ {_r_null_tc} rows missing Task Code — these cannot be reconciled")
with st.expander("🟩 ServiceNow — Data Profile", expanded=True):
    _sn_dates = pd.to_datetime(sn_raw["Date"], errors="coerce")
    _sn_h = pd.to_numeric(sn_raw["Time worked"], errors="coerce").fillna(0)
    _sn_dupes = int(
        sn_clean.duplicated(subset=["date", "sn_user_id", "task_code"]).sum()
    )

    n1, n2, n3, n4 = st.columns(4)
    n1.metric("Total rows", f"{len(sn_raw):,}")
    n2.metric("Sheets loaded", str(sn_raw["_sheet"].nunique()))
    n3.metric("Unique users", str(sn_raw["User ID"].nunique()))
    n4.metric("Unique task codes", str(sn_raw["Project ID"].nunique()))

    st.markdown("")
    n5, n6, n7, n8 = st.columns(4)
    n5.metric("Total hours", f"{_sn_h.sum():,.1f} h")
    n6.metric(
        "Date range",
        f"{_sn_dates.min().date()}",
        delta=f"→ {_sn_dates.max().date()}",
        delta_color="off",
    )
    n7.metric(
        "Duplicate rows",
        str(_sn_dupes),
        delta="check needed" if _sn_dupes > 0 else "none",
        delta_color="inverse" if _sn_dupes > 0 else "off",
    )
    n8.metric("Rows with 0 h", f"{int((_sn_h == 0).sum()):,}")

    st.markdown("")
    st.markdown("**Column null counts**")
    _sn_nulls = pd.DataFrame(
        [
            (
                "Date",
                int(_sn_dates.isna().sum()),
                "❌ fix date format" if _bad_sn else "✅",
            ),
            ("User", int(sn_raw["User"].isna().sum()), "✅"),
            ("User ID", int(sn_raw["User ID"].isna().sum()), "✅"),
            (
                "Project ID",
                int(sn_raw["Project ID"].isna().sum()),
                "⚠️ missing" if sn_raw["Project ID"].isna().any() else "✅",
            ),
            (
                "Time worked",
                int(sn_raw["Time worked"].isna().sum()),
                "⚠️ treated as 0" if sn_raw["Time worked"].isna().any() else "✅",
            ),
        ],
        columns=["Column", "Nulls", "Status"],
    )
    st.dataframe(_sn_nulls, use_container_width=True, hide_index=True)

    st.markdown("**Hours by sheet** (ServiceNow source breakdown)")
    _sn_sheet_h = (
        sn_clean.groupby("_sheet")["hours"]
        .agg(["sum", "count"])
        .reset_index()
        .rename(columns={"_sheet": "Sheet", "sum": "Total Hours", "count": "Rows"})
    )
    _sn_sheet_h["Total Hours"] = _sn_sheet_h["Total Hours"].round(2)
    st.dataframe(_sn_sheet_h, use_container_width=True, hide_index=True)

    if _bad_sn:
        st.error(f"⛔ {_bad_sn} rows have unparseable dates")
    if _sn_dupes > 0:
        st.warning(
            f"⚠️ {_sn_dupes} duplicate (date, user, task_code) rows in ServiceNow"
        )

st.divider()

with st.spinner("Matching users…"):
    user_mapping = _run_matching(
        file_data_tuple,
        sn_upload.getvalue(),
        st.session_state.get("_corrected_map_bytes"),
        auto_accept,
        review_low,
    )

needs_review = user_mapping[user_mapping["review_required"]]
_s2_icon = "✅" if needs_review.empty else "⚠️"

st.subheader(f"{_s2_icon} Step 2 — User Matching")

_ms1, _ms2, _ms3, _ms4 = st.columns(4)
_ms1.metric("Total users", str(len(user_mapping)))
_ms2.metric(
    "Auto-accepted", str(user_mapping["match_status"].eq("auto_accepted").sum())
)
_ms3.metric(
    "Needs review",
    str(len(needs_review)),
    delta="action required" if not needs_review.empty else None,
    delta_color="inverse" if not needs_review.empty else "off",
)
_ms4.metric(
    "No match", str(user_mapping["match_status"].isin(["no_match", "rejected"]).sum())
)

st.markdown("")

_fuzzy_scores = user_mapping[user_mapping["match_method"] == "fuzzy"]["final_score"]
if not _fuzzy_scores.empty:
    _fb1, _fb2, _fb3, _fb4 = st.columns(4)
    _fb1.metric("Fuzzy matches", str(len(_fuzzy_scores)))
    _fb2.metric("Lowest score", f"{_fuzzy_scores.min():.3f}")
    _fb3.metric("Mean score", f"{_fuzzy_scores.mean():.3f}")
    _fb4.metric("Highest score", f"{_fuzzy_scores.max():.3f}")
    st.markdown("")

st.markdown("**Full mapping table**")
st.dataframe(
    user_mapping[
        [
            "replicon_username",
            "servicenow_user_id",
            "servicenow_name",
            "match_method",
            "final_score",
            "match_status",
            "review_required",
        ]
    ],
    use_container_width=True,
    hide_index=True,
    column_config={
        "final_score": st.column_config.ProgressColumn(
            "final_score",
            min_value=0,
            max_value=1,
            format="%.3f",
        ),
        "review_required": st.column_config.CheckboxColumn("review_required"),
    },
)

if not needs_review.empty and not st.session_state.get("proceed_confirmed", False):
    st.divider()
    st.error(
        f"🛑 **{len(needs_review)} user(s) require review** — "
        "reconciliation is paused until these are confirmed or corrected.",
        icon="🛑",
    )

    with st.container(border=True):
        st.markdown("**Rows needing review:**")
        st.dataframe(
            needs_review[
                [
                    "replicon_username",
                    "servicenow_user_id",
                    "servicenow_name",
                    "match_method",
                    "jaro_winkler_score",
                    "token_sort_score",
                    "token_set_score",
                    "final_score",
                    "match_status",
                ]
            ],
            use_container_width=True,
            hide_index=True,
            column_config={
                "final_score": st.column_config.ProgressColumn(
                    "final_score",
                    min_value=0,
                    max_value=1,
                    format="%.3f",
                ),
            },
        )

        st.markdown(
            "**Option A — Fix and re-upload:** download the template, correct "
            "`servicenow_user_id` and set `match_status = auto_accepted`, then upload below."
        )
        _col_dl, _col_up = st.columns(2)
        with _col_dl:
            st.download_button(
                "📥 Download mapping template",
                data=_excel_bytes(user_mapping),
                file_name=f"user_mapping_review_{_TS}.xlsx",
                mime=_MIME,
                use_container_width=True,
            )
        with _col_up:
            _corrected = st.file_uploader(
                "📤 Upload corrected mapping",
                type=["xlsx"],
                key="corrected_mapping_uploader",
            )
            if _corrected:
                _new = _corrected.getvalue()
                if _new != st.session_state.get("_corrected_map_bytes"):
                    st.session_state._corrected_map_bytes = _new
                    st.rerun()

        st.markdown("**Option B — Proceed anyway:**")
        if st.checkbox(
            "I understand these matches are uncertain — proceed and flag them in the output",
            key="proceed_confirmed",
        ):
            st.rerun()

    st.stop()

st.divider()

st.subheader("⏳ Step 3 — Running Reconciliation…")
_prog = st.progress(0, text="Aggregating and reconciling…")

try:
    results = _run_full(
        file_data_tuple,
        sn_upload.getvalue(),
        user_mapping,
        auto_accept,
        review_low,
    )
except Exception as exc:
    st.error(f"Reconciliation failed: {exc}")
    st.stop()

_prog.progress(100, text="Done")
_prog.empty()

st.subheader("✅ Step 3 — Reconciliation Complete")

s = results["summary"].set_index("metric")["value"].to_dict()

with st.expander("📐 Data Scoping & Aggregation Checks", expanded=True):
    st.markdown(
        "**ServiceNow rows funnel — how SN data is narrowed to match the Replicon extract**"
    )
    _sc1, _sc2, _sc3, _sc4, _sc5 = st.columns(5)
    _sc1.metric("SN rows loaded", f"{int(s['total_servicenow_rows_loaded']):,}")
    _sc2.metric(
        "− date filter",
        f"{int(s['total_servicenow_rows_excluded_by_date']):,}",
        delta=f"kept {s['replicon_window_start']} → {s['replicon_window_end']}",
        delta_color="off",
    )
    _sc3.metric(
        "− user filter",
        f"{int(s['total_servicenow_rows_excluded_by_user']):,}",
        delta="SN-only users removed",
        delta_color="off",
    )
    _sc4.metric(
        "− task filter",
        f"{int(s['total_servicenow_rows_excluded_by_task']):,}",
        delta="SN-only task codes removed",
        delta_color="off",
    )
    _sc5.metric("Rows in scope ✓", f"{int(s['total_servicenow_rows_in_window']):,}")

    st.markdown("")
    st.markdown("**Hours tieout — hours must not change during aggregation**")
    _rep_ok = (
        abs(
            float(s["total_replicon_hours_before_aggregation"])
            - float(s["total_replicon_hours_after_aggregation"])
        )
        < 0.01
    )
    _sn_ok = (
        abs(
            float(s["total_servicenow_hours_in_window"])
            - float(s["total_servicenow_hours_after_aggregation"])
        )
        < 0.01
    )

    _ag1, _ag2, _ag3, _ag4 = st.columns(4)
    _ag1.metric(
        "Replicon before agg",
        f"{float(s['total_replicon_hours_before_aggregation']):.2f} h",
    )
    _ag2.metric(
        "Replicon after agg",
        f"{float(s['total_replicon_hours_after_aggregation']):.2f} h",
        delta="✅ matches" if _rep_ok else "❌ mismatch",
        delta_color="off" if _rep_ok else "inverse",
    )
    _ag3.metric(
        "ServiceNow in scope", f"{float(s['total_servicenow_hours_in_window']):.2f} h"
    )
    _ag4.metric(
        "ServiceNow after agg",
        f"{float(s['total_servicenow_hours_after_aggregation']):.2f} h",
        delta="✅ matches" if _sn_ok else "❌ mismatch",
        delta_color="off" if _sn_ok else "inverse",
    )

    if not _rep_ok or not _sn_ok:
        st.error(
            "⛔ Hours do not tie before and after aggregation — investigate for duplicates before trusting results"
        )

st.markdown("---")
c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric(
    "Replicon Hours", f"{float(s['total_replicon_hours_after_aggregation']):,.1f} h"
)
c2.metric(
    "ServiceNow Hours", f"{float(s['total_servicenow_hours_after_aggregation']):,.1f} h"
)
c3.metric(
    "Net Variance",
    f"{float(s['net_variance']):+,.2f} h",
    delta_color="inverse" if float(s["net_variance"]) != 0 else "off",
)
c4.metric(
    "Users Matched",
    f"{int(s['total_users_matched'])} / {int(s['total_users_matched']) + int(s['total_users_unmatched'])}",
)
c5.metric("Records Compared", f"{int(s['total_records_compared']):,}")
c6.metric("Discrepancies", f"{int(s['total_discrepancies']):,}")
st.caption(
    f"Period: **{s['replicon_window_start']}** → **{s['replicon_window_end']}**  |  "
    "Grain: `date × user × task_code`"
)

months = list(results["recon_by_month"].keys())
tab_names = (
    ["📋 Summary", "👥 By User"]
    + [f"📅 {m}" for m in months]
    + ["⚠️ Exceptions", "🔗 User Mapping", "🔍 Detail"]
)
tab_summary, tab_by_user, *tab_months, tab_exc, tab_map, tab_detail = st.tabs(tab_names)

with tab_summary:
    _tl, _tr = st.columns(2)
    with _tl:
        st.dataframe(results["summary"], use_container_width=True, hide_index=True)
    with _tr:
        if not needs_review.empty:
            st.warning(
                f"⚠️ {len(needs_review)} user(s) proceeded with uncertain matches"
            )
            st.dataframe(
                needs_review[
                    [
                        "replicon_username",
                        "servicenow_user_id",
                        "match_method",
                        "final_score",
                    ]
                ],
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.success("✅ All users matched and confirmed")
        _dup = results["dup_sn"]
        if not _dup.empty:
            st.error("⛔ Duplicate SN→Replicon mappings:")
            st.dataframe(_dup.reset_index(), use_container_width=True, hide_index=True)

with tab_by_user:
    st.dataframe(results["recon_by_user"], use_container_width=True, hide_index=True)

for tab_month, month in zip(tab_months, months):
    with tab_month:
        st.dataframe(
            results["recon_by_month"][month], use_container_width=True, hide_index=True
        )

with tab_exc:
    exc = results["exception_report"]
    if exc.empty:
        st.success("✅ No exceptions found")
    else:
        _et = exc["exception_type"].dropna().unique().tolist()
        _sel = st.multiselect("Filter by type", _et, default=_et, key="exc_filter")
        _flt = exc[exc["exception_type"].isin(_sel)] if _sel else exc
        _a, _b = st.columns([3, 1])
        _a.caption(f"{len(_flt):,} rows")
        _b.metric("Variance in view", f"{_flt['variance'].sum():+.2f} h")
        st.dataframe(_flt, use_container_width=True, hide_index=True)

with tab_map:
    st.caption(
        "Fix wrong matches here: download → correct `servicenow_user_id`, "
        "set `match_status = auto_accepted` → re-upload in Step 2."
    )
    st.dataframe(results["user_mapping"], use_container_width=True, hide_index=True)

with tab_detail:
    _uf, _vf = st.columns([3, 1])
    with _uf:
        _user_filter = st.multiselect(
            "Filter by user",
            sorted(results["recon_table"]["user_id"].dropna().unique()),
            key="detail_user_filter",
        )
    with _vf:
        _var_only = st.checkbox("Variance rows only", key="detail_var_only")

    _detail = results["recon_table"]
    if _user_filter:
        _detail = _detail[_detail["user_id"].isin(_user_filter)]
    if _var_only:
        _detail = _detail[_detail["variance"] != 0]
    st.caption(f"{len(_detail):,} rows")
    st.dataframe(_detail, use_container_width=True, hide_index=True)

st.divider()
st.subheader("📥 Downloads")
d1, d2, d3, d4 = st.columns(4)
with d1:
    st.download_button(
        "Reconciliation (all sheets)",
        data=rec.to_excel_bytes(results),
        file_name=f"reconciliation_{_TS}.xlsx",
        mime=_MIME,
        use_container_width=True,
        help="Includes: detail, by_user, one sheet per month",
    )
with d2:
    st.download_button(
        "Exception Report",
        data=_excel_bytes(results["exception_report"]),
        file_name=f"exception_report_{_TS}.xlsx",
        mime=_MIME,
        use_container_width=True,
    )
with d3:
    st.download_button(
        "User Mapping",
        data=_excel_bytes(results["user_mapping"]),
        file_name=f"user_mapping_{_TS}.xlsx",
        mime=_MIME,
        use_container_width=True,
        help="Fix wrong matches here and re-upload in Step 2",
    )
with d4:
    st.download_button(
        "Summary",
        data=_excel_bytes(results["summary"]),
        file_name=f"summary_{_TS}.xlsx",
        mime=_MIME,
        use_container_width=True,
    )
