"""Golden fixture tests.

Any diff in the golden files must be explained in the change description before
the file is regenerated.  These tests catch silent semantic changes.
"""

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.mappings import normalise_name
from src.transformations import clean_replicon

GOLDEN_DIR = Path(__file__).parent / "golden"


class TestNormaliseNameGolden:
    def test_matches_golden_fixture(self):
        golden = json.loads((GOLDEN_DIR / "normalise_name.json").read_text())
        for inp, expected in golden.items():
            assert normalise_name(inp) == expected, (
                f"normalise_name({inp!r}) changed: expected {expected!r}"
            )


class TestCleanRepliconGolden:
    def _raw(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "Entry Date": ["01.06.2026", "02.06.2026", "not-a-date"],
                "User Name": ["Alice Smith", "Bob Jones", "Carol White"],
                "Employee ID": ["E001", "E002.0", None],
                "Project Code": ["P1", "P1", "P2"],
                "Task Code": ["T001", "T002", "T003"],
                "Hours": ["8", "", "7.5"],
                "_source_file": ["a.csv", "a.csv", "a.csv"],
            }
        )

    def test_matches_golden_fixture(self):
        golden = json.loads((GOLDEN_DIR / "clean_replicon.json").read_text())
        result = clean_replicon(self._raw())
        for i, expected_row in enumerate(golden):
            row = result.iloc[i]
            assert row["username"] == expected_row["username"], f"row {i} username mismatch"
            assert row["hours"] == pytest.approx(expected_row["hours"]), f"row {i} hours mismatch"
            if expected_row["employee_id"] is None:
                assert pd.isna(row["employee_id"]), f"row {i} employee_id should be null"
            else:
                assert row["employee_id"] == expected_row["employee_id"], (
                    f"row {i} employee_id mismatch"
                )
