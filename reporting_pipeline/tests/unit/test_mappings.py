"""
Tests for name normalisation and user mapping functions.
"""

import pandas as pd

from src.mappings import build_user_mapping, normalise_name, normalise_uid

# ── normalise_name ────────────────────────────────────────────────────────────


class TestNormaliseName:
    def test_lowercases(self):
        assert normalise_name("John Smith") == "john smith"

    def test_removes_parentheses(self):
        assert normalise_name("John Smith (Contractor)") == "john smith"

    def test_converts_last_first_format(self):
        assert normalise_name("Smith, John") == "john smith"

    def test_strips_punctuation(self):
        # "O'Brien, Sean" → Last,First swap → "Sean O Brien" → lowercase + strip punctuation
        assert normalise_name("O'Brien, Sean") == "sean o brien"

    def test_handles_non_string(self):
        assert normalise_name(None) == ""
        assert normalise_name(123) == ""


# ── normalise_uid ─────────────────────────────────────────────────────────────


class TestNormaliseUid:
    def test_strips_email_domain(self):
        assert normalise_uid("jsmith@example.com") == "jsmith"

    def test_lowercases(self):
        assert normalise_uid("JSmith") == "jsmith"

    def test_replaces_separators_with_space(self):
        assert normalise_uid("john.smith") == "john smith"
        assert normalise_uid("john_smith") == "john smith"
        assert normalise_uid("john-smith") == "john smith"

    def test_handles_non_string(self):
        assert normalise_uid(None) == ""


# ── build_user_mapping ────────────────────────────────────────────────────────


class TestBuildUserMapping:
    def _make_replicon_users(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "username": ["John Smith", "Jane Doe"],
                "employee_id": ["E001", "E002"],
                "norm_name": ["john smith", "jane doe"],
            }
        )

    def _make_sn_users(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "sn_user": ["John Smith", "Jane Doe"],
                "sn_user_id": ["jsmith", "jdoe"],
                "norm_name": ["john smith", "jane doe"],
                "norm_uid": ["jsmith", "jdoe"],
            }
        )

    def test_exact_match_auto_accepted(self):
        mapping = build_user_mapping(self._make_replicon_users(), self._make_sn_users())
        assert all(mapping["match_status"] == "auto_accepted")
        assert all(mapping["match_method"] == "exact_name")

    def test_no_match_for_unknown_user(self):
        rep = pd.DataFrame(
            {
                "username": ["Unknown Person"],
                "employee_id": ["E999"],
                "norm_name": ["unknown person"],
            }
        )
        mapping = build_user_mapping(rep, self._make_sn_users())
        assert mapping.iloc[0]["match_status"] in ("no_match", "review_required", "rejected")

    def test_returns_expected_columns(self):
        mapping = build_user_mapping(self._make_replicon_users(), self._make_sn_users())
        expected = {
            "replicon_username",
            "servicenow_user_id",
            "match_method",
            "final_score",
            "match_status",
            "review_required",
        }
        assert expected.issubset(set(mapping.columns))

    def test_row_count_matches_input(self):
        mapping = build_user_mapping(self._make_replicon_users(), self._make_sn_users())
        assert len(mapping) == 2


class TestNormalisationSymmetry:
    """Normalisation must be idempotent and consistent."""

    def test_normalise_name_idempotent(self):
        name = "john smith"
        assert normalise_name(normalise_name(name)) == normalise_name(name)

    def test_normalise_uid_idempotent(self):
        uid = "john smith"
        assert normalise_uid(normalise_uid(uid)) == normalise_uid(uid)

    def test_last_first_equals_first_last_after_normalisation(self):
        assert normalise_name("Smith, John") == normalise_name("John Smith")


class TestMatchUsers:
    def _make_cleaned_frames(self) -> tuple:
        from src.transformations import clean_replicon, clean_servicenow

        rep_raw = pd.DataFrame(
            {
                "Entry Date": ["01.06.2026"],
                "User Name": ["John Smith"],
                "Employee ID": ["E001"],
                "Project Code": ["P1"],
                "Task Code": ["T1"],
                "Hours": ["8"],
            }
        )
        sn_raw = pd.DataFrame(
            {
                "Date": ["2026-06-01"],
                "User": ["John Smith"],
                "User ID": ["jsmith"],
                "Project ID": ["T1"],
                "Time worked": [8],
                "_sheet": ["S1"],
            }
        )
        return clean_replicon(rep_raw), clean_servicenow(sn_raw)

    def test_match_users_returns_dataframe(self):
        from src.mappings import match_users

        rep, sn = self._make_cleaned_frames()
        mapping = match_users(rep, sn)
        assert isinstance(mapping, pd.DataFrame)

    def test_match_users_exact_name_auto_accepted(self):
        from src.mappings import match_users

        rep, sn = self._make_cleaned_frames()
        mapping = match_users(rep, sn)
        assert mapping.iloc[0]["match_status"] == "auto_accepted"

    def test_approved_mapping_overrides_auto_match(self):
        from src.mappings import match_users

        rep, sn = self._make_cleaned_frames()
        approved = pd.DataFrame(
            {
                "replicon_username": ["John Smith"],
                "servicenow_user_id": ["manual_id"],
                "match_status": ["auto_accepted"],
                "replicon_employee_id": ["E001"],
                "review_required": [False],
            }
        )
        mapping = match_users(rep, sn, approved=approved)
        row = mapping[mapping["replicon_username"] == "John Smith"].iloc[0]
        assert row["servicenow_user_id"] == "manual_id"
