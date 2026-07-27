"""Tests for FTE data preparation."""

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.fte_prep import prepare_fte_data


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

TECH_MAP  = {"Tech A": "Group A", "Tech B": "Group B"}
TASK_CATS = ["Task work", "Sick/Holiday"]


def _make_timecard(rows: list[dict]) -> pd.DataFrame:
    week = pd.Timestamp("2026-06-02")  # Monday
    defaults = {
        "Date":           week,
        "week_start":     week,
        "User ID":        "u1",
        "User":           "User One",
        "Time worked":    8.0,
        "Category":       "Task work",
        "Task":           "T001",
        "Rate type":      "Standard",
        "Technology":     "Tech A",
        "Specialisation": "Spec A",
        "is_gen":         False,
    }
    records = [{**defaults, **r} for r in rows]
    df = pd.DataFrame(records)
    df["Date"] = pd.to_datetime(df["Date"])
    df["week_start"] = pd.to_datetime(df["week_start"])
    return df


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPrepareFteData:
    def test_returns_required_keys(self):
        df = _make_timecard([{}])
        result = prepare_fte_data(df, 34.0, (100, 119), TECH_MAP, TASK_CATS)
        for key in ("weekly", "graph1", "graph2", "pivot", "tech_weekly_no_gen"):
            assert key in result

    def test_total_fte_calculation(self):
        df = _make_timecard([{"Time worked": 34.0}])
        result = prepare_fte_data(df, 34.0, (100, 119), TECH_MAP, TASK_CATS)
        row = result["weekly"].iloc[0]
        assert abs(row["total_fte"] - 1.0) < 0.01

    def test_task_fte_excludes_gen(self):
        df = _make_timecard([
            {"Time worked": 20.0, "Task": "TASK1",  "is_gen": False, "Category": "Task work"},
            {"Time worked": 14.0, "Task": "GENBENCH","is_gen": True,  "Category": "Task work"},
        ])
        result = prepare_fte_data(df, 34.0, (100, 119), TECH_MAP, TASK_CATS)
        row = result["weekly"].iloc[0]
        # task_fte covers Task work (non-GEN) + Sick/Holiday; gen_fte covers GEN
        assert abs(row["task_hours"] - 20.0) < 0.01
        assert abs(row["gen_hours"]  - 14.0) < 0.01

    def test_gen_pct_calculation(self):
        df = _make_timecard([
            {"Time worked": 17.0, "Task": "T1",       "is_gen": False, "Category": "Task work"},
            {"Time worked": 17.0, "Task": "GENOVERH", "is_gen": True,  "Category": "Task work"},
        ])
        result = prepare_fte_data(df, 34.0, (100, 119), TECH_MAP, TASK_CATS)
        pct = result["weekly"].iloc[0]["gen_pct"]
        assert abs(pct - 50.0) < 0.5

    def test_in_band_true_when_within_range(self):
        # 101 FTE at 34 h/FTE = 3434 h
        df = _make_timecard([{"Time worked": 3434.0}])
        result = prepare_fte_data(df, 34.0, (100, 119), TECH_MAP, TASK_CATS)
        assert bool(result["weekly"].iloc[0]["in_band"]) is True

    def test_in_band_false_when_outside_range(self):
        df = _make_timecard([{"Time worked": 100.0}])
        result = prepare_fte_data(df, 34.0, (100, 119), TECH_MAP, TASK_CATS)
        assert bool(result["weekly"].iloc[0]["in_band"]) is False

    def test_graph1_has_fte_band_columns(self):
        df = _make_timecard([{}])
        result = prepare_fte_data(df, 34.0, (100, 119), TECH_MAP, TASK_CATS)
        assert "fte_lower" in result["graph1"].columns
        assert "fte_upper" in result["graph1"].columns
        assert result["graph1"].iloc[0]["fte_lower"] == 100
        assert result["graph1"].iloc[0]["fte_upper"] == 119

    def test_tech_group_mapping_applied(self):
        df = _make_timecard([{"Technology": "Tech A", "Category": "Task work", "is_gen": False}])
        result = prepare_fte_data(df, 34.0, (100, 119), TECH_MAP, TASK_CATS)
        groups = result["tech_weekly_no_gen"]["tech_group"].unique()
        assert "Group A" in groups

    def test_unknown_technology_mapped_to_other(self):
        df = _make_timecard([{"Technology": "Unknown Tech XYZ", "Category": "Task work", "is_gen": False}])
        result = prepare_fte_data(df, 34.0, (100, 119), TECH_MAP, TASK_CATS)
        groups = result["tech_weekly"]["tech_group"].unique()
        assert "Other" in groups

    def test_hours_do_not_change_in_weekly_aggregation(self):
        df = _make_timecard([
            {"Time worked": 5.5},
            {"Time worked": 3.5},
        ])
        result = prepare_fte_data(df, 34.0, (100, 119), TECH_MAP, TASK_CATS)
        assert abs(result["weekly"].iloc[0]["total_hours"] - 9.0) < 0.01
