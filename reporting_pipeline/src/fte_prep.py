"""Weekly FTE aggregation for Power BI. Equivalent of powerbi_fte_data_prep.ipynb."""

import logging
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

def prepare_fte_data(
    df: pd.DataFrame,
    hours_per_fte: float,
    fte_band: tuple,
    tech_map: dict,
    task_categories: list,
) -> dict:
    """Aggregate cleaned time-card data into weekly FTE metrics by tech group."""
    wk = df.dropna(subset=["week_start"])

    weekly = (
        pd.concat(
            [
                wk.groupby("week_start")["Time worked"].sum().rename("total_hours"),
                wk[~wk["is_gen"] & wk["Category"].isin(task_categories)]
                .groupby("week_start")["Time worked"].sum().rename("task_hours"),
                wk[wk["is_gen"]].groupby("week_start")["Time worked"].sum().rename("gen_hours"),
            ],
            axis=1,
        )
        .fillna(0)
        .assign(
            total_fte=lambda d: (d["total_hours"] / hours_per_fte).round(2),
            task_fte=lambda d: (d["task_hours"] / hours_per_fte).round(2),
            gen_fte=lambda d: (d["gen_hours"] / hours_per_fte).round(2),
            gen_pct=lambda d: (
                d["gen_hours"] / d["total_hours"].replace(0, float("nan")) * 100
            ).round(1).fillna(0),
            in_band=lambda d: (d["total_hours"] / hours_per_fte).between(*fte_band),
            month=lambda d: d.index.to_period("M").astype(str),
            total_hours=lambda d: d["total_hours"].round(2),
            task_hours=lambda d: d["task_hours"].round(2),
            gen_hours=lambda d: d["gen_hours"].round(2),
        )
        .reset_index()
        .assign(
            week_end=lambda d: d["week_start"] + pd.Timedelta(days=6),
            week=lambda d: (
                d["week_start"].dt.strftime("%d %b")
                + " – "
                + (d["week_start"] + pd.Timedelta(days=6)).dt.strftime("%d %b %Y")
            ),
        )
    )

    logger.info(
        "FTE weekly summary: %d weeks  %s to %s",
        len(weekly),
        weekly["week_start"].min().date(),
        weekly["week_start"].max().date(),
    )

    w = weekly.assign(
        week_start=weekly["week_start"].dt.strftime("%Y-%m-%d"),
        week_end=weekly["week_end"].dt.strftime("%Y-%m-%d"),
    )

    graph1 = w[
        ["week_start", "week_end", "week", "month", "total_hours", "total_fte", "in_band"]
    ].assign(fte_lower=fte_band[0], fte_upper=fte_band[1])

    graph2 = w[
        ["week_start", "week_end", "week", "month", "task_hours", "task_fte",
         "gen_hours", "gen_fte", "gen_pct"]
    ]

    df_pivot = df.dropna(subset=["week_start", "Category"]).copy()
    df_pivot["Category"] = np.where(
        df_pivot["is_gen"],
        df_pivot["Category"] + " (GEN)",
        df_pivot["Category"],
    )
    pivot = (
        df_pivot.pivot_table(
            index="Category",
            columns="week_start",
            values="Time worked",
            aggfunc="sum",
            margins=True,
            margins_name="Grand Total",
        )
        .round(2)
    )
    pivot.columns = [
        c.strftime("%-d/%-m/%Y") if isinstance(c, pd.Timestamp) else c
        for c in pivot.columns
    ]

    week_labels = weekly[["week_start", "week_end", "week", "month"]].copy()

    df_tech = df.dropna(subset=["week_start", "Technology"]).copy()
    df_tech["tech_group"] = df_tech["Technology"].map(tech_map).fillna("Other")
    df_tech["specialisation"] = df_tech["Specialisation"].fillna("Unknown")

    df_sick = df[
        df["Category"].isin(["Sick/Holiday"]) & ~df["is_gen"] & df["week_start"].notna()
    ].copy()
    df_sick["tech_group"] = "Sick/Holiday"
    df_sick["specialisation"] = "N/A"

    tech_weekly = _build_tech_weekly(df_tech, week_labels, hours_per_fte, by_spec=False)
    tech_weekly_spec = _build_tech_weekly(df_tech, week_labels, hours_per_fte, by_spec=True)

    df_tech_no_gen = pd.concat(
        [
            df_tech[(df_tech["Category"] == "Task work") & (~df_tech["is_gen"])],
            df_sick,
        ],
        ignore_index=True,
    )
    tech_weekly_no_gen = _build_tech_weekly(df_tech_no_gen, week_labels, hours_per_fte, by_spec=False)
    tech_weekly_spec_no_gen = _build_tech_weekly(df_tech_no_gen, week_labels, hours_per_fte, by_spec=True)

    return {
        "weekly": weekly,
        "graph1": graph1,
        "graph2": graph2,
        "pivot": pivot,
        "tech_weekly": tech_weekly,
        "tech_weekly_spec": tech_weekly_spec,
        "tech_weekly_no_gen": tech_weekly_no_gen,
        "tech_weekly_spec_no_gen": tech_weekly_spec_no_gen,
    }

def _build_tech_weekly(
    source: pd.DataFrame,
    week_labels: pd.DataFrame,
    hours_per_fte: float,
    by_spec: bool = False,
) -> pd.DataFrame:
    group_cols = ["week_start", "tech_group"] + (["specialisation"] if by_spec else [])
    out = (
        source.groupby(group_cols)["Time worked"]
        .sum()
        .reset_index()
        .rename(columns={"Time worked": "hours"})
    )
    out["fte"] = (out["hours"] / hours_per_fte).round(2)
    out["hours"] = out["hours"].round(2)
    out = out.merge(week_labels, on="week_start", how="left")
    out["week_start"] = out["week_start"].dt.strftime("%Y-%m-%d")
    out["week_end"] = out["week_end"].dt.strftime("%Y-%m-%d")
    col_order = (
        ["week_start", "week_end", "week", "month", "tech_group"]
        + (["specialisation"] if by_spec else [])
        + ["hours", "fte"]
    )
    return out[col_order].sort_values(group_cols).reset_index(drop=True)

def validate_against_reference(
    weekly: pd.DataFrame,
    ref_graph2_path: Optional[Path],
    ref_graph1_path: Optional[Path],
) -> None:
    """Compare computed FTE figures against reference CSVs. Logs a warning if any week differs by >0.1%."""
    for ref_path, our_hours_col, our_fte_col, label in [
        (ref_graph2_path, "task_hours", "task_fte", "Graph 2 (no-GEN)"),
        (ref_graph1_path, "total_hours", "total_fte", "Graph 1 (with GEN)"),
    ]:
        if ref_path is None or not Path(ref_path).exists():
            continue
        ref = pd.read_csv(ref_path)
        ref["week_start"] = pd.to_datetime(ref["week"], format="%m/%d/%Y")
        m = weekly.merge(ref[["week_start", "ref_hours", "ref_fte"]], on="week_start", how="inner")
        m["Δ_hours"] = (m[our_hours_col] - m["ref_hours"]).round(2)
        m["Δ_pct"] = (m["Δ_hours"].abs() / m["ref_hours"] * 100).round(1)

        exact = (m["Δ_pct"] < 0.1).sum()
        close = (m["Δ_pct"] <= 1.0).sum()
        logger.info(
            "%s: %d weeks | exact=%d  close=%d  avg diff=%.1f h  max diff=%.1f h",
            label, len(m), exact, close, m["Δ_hours"].mean(), m["Δ_hours"].abs().max(),
        )
        diffs = m[m["Δ_pct"] > 0.1]
        if len(diffs):
            logger.warning("%s: %d week(s) differ by more than 0.1%%:", label, len(diffs))
            for _, row in diffs.iterrows():
                logger.warning(
                    "  %s  our=%.2f h  ref=%.2f h  diff=%.2f h (%.1f%%)",
                    row["week_start"].date(), row[our_hours_col], row["ref_hours"],
                    row["Δ_hours"], row["Δ_pct"],
                )
