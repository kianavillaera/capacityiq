"""Name normalisation and Replicon-to-ServiceNow user matching."""

import logging
import re
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

try:
    import jellyfish

    HAS_JELLYFISH = True
except ImportError:
    jellyfish: Any = None  # type: ignore[no-redef]
    HAS_JELLYFISH = False

try:
    from rapidfuzz import fuzz as _rf

    HAS_RAPIDFUZZ = True
except ImportError:
    _rf: Any = None  # type: ignore[no-redef]
    HAS_RAPIDFUZZ = False


def normalise_name(name: str) -> str:
    """Normalise a display name for matching. Handles 'Last, First' format and strips punctuation."""
    if not isinstance(name, str):
        return ""
    name = re.sub(r"\(.*?\)", "", name)
    if "," in name:
        last, first = name.split(",", 1)
        name = first.strip() + " " + last.strip()
    name = name.lower()
    name = re.sub(r"[^\w\s]", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def normalise_uid(uid: str) -> str:
    """Normalise a user ID or email for matching. Strips domain, lowercases, replaces separators."""
    if not isinstance(uid, str):
        return ""
    uid = re.sub(r"@.*$", "", uid)
    uid = uid.lower().strip()
    uid = re.sub(r"[._\-]", " ", uid)
    uid = re.sub(r"\s+", " ", uid).strip()
    return uid


def _best_score(rep_norm: str, sn_norm: str, sn_uid: str) -> tuple:
    # Composite score: 35% Jaro-Winkler + 30% token-sort + 35% token-set.
    # Each metric is computed against both the SN display name and SN uid; best wins.
    def _s(a: str, b: str) -> tuple:
        jw = jellyfish.jaro_winkler_similarity(a, b) if HAS_JELLYFISH and jellyfish else 0.0
        ts = _rf.token_sort_ratio(a, b) / 100 if HAS_RAPIDFUZZ and _rf else 0.0
        tst = _rf.token_set_ratio(a, b) / 100 if HAS_RAPIDFUZZ and _rf else 0.0
        return jw, ts, tst

    jw1, ts1, tst1 = _s(rep_norm, sn_norm)
    jw2, ts2, tst2 = _s(rep_norm, sn_uid)
    jw = max(jw1, jw2)
    ts = max(ts1, ts2)
    tst = max(tst1, tst2)

    if HAS_JELLYFISH and HAS_RAPIDFUZZ:
        final = 0.35 * jw + 0.30 * ts + 0.35 * tst
    elif HAS_JELLYFISH:
        final = jw
    elif HAS_RAPIDFUZZ:
        final = 0.5 * ts + 0.5 * tst
    else:
        final = 0.0

    return jw, ts, tst, final


def build_user_mapping(
    rep_df: pd.DataFrame,
    sn_df: pd.DataFrame,
    auto_accept: float = 0.80,
    review_low: float = 0.70,
) -> pd.DataFrame:
    """Match each Replicon user to a ServiceNow user.

    Priority: exact name match > exact UID match > best fuzzy score.
    Fuzzy matches below review_low are rejected; between review_low and
    auto_accept they are flagged for review.
    """
    sn_by_name = dict(zip(sn_df["norm_name"], sn_df["sn_user_id"]))
    sn_by_uid = dict(zip(sn_df["norm_uid"], sn_df["sn_user_id"]))

    rows = []
    for _, rep in rep_df.iterrows():
        rn = rep["norm_name"]
        record: dict = {
            "replicon_username": rep["username"],
            "replicon_employee_id": rep["employee_id"],
            "servicenow_user_id": None,
            "servicenow_name": None,
            "match_method": "no_match",
            "jaro_winkler_score": 0.0,
            "token_sort_score": 0.0,
            "token_set_score": 0.0,
            "final_score": 0.0,
            "review_required": True,
            "match_status": "no_match",
            "notes": "",
        }

        if rn in sn_by_name:
            uid = sn_by_name[rn]
            record.update(
                servicenow_user_id=uid,
                match_method="exact_name",
                jaro_winkler_score=1.0,
                token_sort_score=1.0,
                token_set_score=1.0,
                final_score=1.0,
                review_required=False,
                match_status="auto_accepted",
            )
        elif rn in sn_by_uid:
            uid = sn_by_uid[rn]
            record.update(
                servicenow_user_id=uid,
                match_method="exact_uid",
                jaro_winkler_score=1.0,
                token_sort_score=1.0,
                token_set_score=1.0,
                final_score=1.0,
                review_required=False,
                match_status="auto_accepted",
            )
        else:
            candidates = []
            for _, sn_row in sn_df.iterrows():
                jw, ts, tst, final = _best_score(rn, sn_row["norm_name"], sn_row["norm_uid"])
                if final >= review_low * 0.70:
                    candidates.append((final, jw, ts, tst, sn_row["sn_user_id"], sn_row["sn_user"]))
            if candidates:
                candidates.sort(reverse=True)
                final, jw, ts, tst, uid, sn_name = candidates[0]
                if final >= auto_accept:
                    status, review, keep = "auto_accepted", False, True
                elif final >= review_low:
                    status, review, keep = "review_required", True, True
                else:
                    status, review, keep = "rejected", True, False
                    uid, sn_name = None, None

                record.update(
                    servicenow_user_id=uid if keep else None,
                    servicenow_name=sn_name if keep else None,
                    match_method="fuzzy",
                    jaro_winkler_score=round(jw, 4),
                    token_sort_score=round(ts, 4),
                    token_set_score=round(tst, 4),
                    final_score=round(final, 4),
                    review_required=review,
                    match_status=status,
                )

        if record["servicenow_user_id"] and not record["servicenow_name"]:
            _row = sn_df[sn_df["sn_user_id"] == record["servicenow_user_id"]]
            if not _row.empty:
                record["servicenow_name"] = _row.iloc[0]["sn_user"]

        rows.append(record)

    mapping = pd.DataFrame(rows)
    logger.info(
        "User mapping built: %d users  |  auto_accepted=%d  review_required=%d  no_match=%d",
        len(mapping),
        mapping["match_status"].eq("auto_accepted").sum(),
        mapping["match_status"].eq("review_required").sum(),
        mapping["match_status"].isin(["no_match", "rejected"]).sum(),
    )
    return mapping


def _user_tables(replicon: pd.DataFrame, sn: pd.DataFrame) -> tuple:
    replicon_users = (
        replicon[["username", "employee_id"]]
        .drop_duplicates(subset=["username"])
        .reset_index(drop=True)
        .assign(norm_name=lambda d: d["username"].map(normalise_name))
    )
    sn_users = (
        sn[["sn_user", "sn_user_id"]]
        .drop_duplicates(subset=["sn_user_id"])
        .reset_index(drop=True)
        .assign(
            norm_name=lambda d: d["sn_user"].map(normalise_name),
            norm_uid=lambda d: d["sn_user_id"].map(normalise_uid),
        )
    )
    return replicon_users, sn_users


def _resolve_mapping(
    replicon_users: pd.DataFrame,
    sn_users: pd.DataFrame,
    approved: pd.DataFrame | None,
    auto_accept: float,
    review_low: float,
) -> tuple:
    if approved is not None:
        mapping = approved.copy()
        unmatched = replicon_users[
            ~replicon_users["username"].isin(set(mapping["replicon_username"]))
        ]
        if not unmatched.empty:
            mapping = pd.concat(
                [
                    mapping,
                    build_user_mapping(unmatched, sn_users, auto_accept, review_low),
                ],
                ignore_index=True,
            )
    else:
        mapping = build_user_mapping(replicon_users, sn_users, auto_accept, review_low)

    dup_sn = (
        mapping[mapping["servicenow_user_id"].notna()]
        .groupby("servicenow_user_id")["replicon_username"]
        .count()
        .loc[lambda x: x > 1]
    )
    if not dup_sn.empty:
        mapping.loc[mapping["servicenow_user_id"].isin(dup_sn.index), "notes"] = (
            "duplicate_user_candidate"
        )

    return mapping, dup_sn


def match_users(
    replicon: pd.DataFrame,
    sn: pd.DataFrame,
    approved: pd.DataFrame | None = None,
    auto_accept: float = 0.80,
    review_low: float = 0.70,
) -> pd.DataFrame:
    """Build the Replicon-to-ServiceNow user mapping. Public entry point."""
    replicon_users, sn_users = _user_tables(replicon, sn)
    mapping, _ = _resolve_mapping(replicon_users, sn_users, approved, auto_accept, review_low)
    return mapping


def match_roster_to_timecard(
    resources: pd.DataFrame,
    tc: pd.DataFrame,
    uid_overrides: dict | None = None,
) -> pd.DataFrame:
    """Match resource roster members to time-card users by UID and normalised name."""
    res = resources.copy()
    tc_uid_by_norm = tc.drop_duplicates("_uid").set_index("_norm")["_uid"]

    res["tc_uid"] = res["_uid"].where(
        res["_uid"].isin(tc["_uid"]),
        res["_norm"].map(tc_uid_by_norm),
    )

    # tc_uid_override column in Resources.xlsx takes precedence over .env overrides
    if "tc_uid_override" in res.columns:
        override_mask = (
            res["tc_uid_override"].notna()
            & (res["tc_uid_override"].astype(str).str.strip() != "")
            & res["tc_uid"].isna()
        )
        res.loc[override_mask, "tc_uid"] = (
            res.loc[override_mask, "tc_uid_override"].str.strip().str.lower()
        )

    # .env uid_overrides as fallback for anything still unmatched
    if uid_overrides:
        for uid, name in uid_overrides.items():
            res.loc[(res["Name"] == name) & res["tc_uid"].isna(), "tc_uid"] = uid

    matched = res["tc_uid"].notna().sum()
    logger.info("Roster matching: %d/%d resources matched to time-card UIDs", matched, len(res))
    return res
