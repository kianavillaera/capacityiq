"""Central configuration -- paths, thresholds, and constants.

Sensitive values (roster sheet name, UID overrides, exception names) are loaded
from a local .env file so they are never committed to source control.
Copy .env.example → .env and fill in your values before running the pipeline.
"""

import json
import os
from pathlib import Path
from datetime import datetime

# Load .env from the project root (silently ignored if the file doesn't exist).
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass  # dotenv not installed — fall back to env vars already in the shell

BASE_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = BASE_DIR / "data"
INPUT_DIR = DATA_DIR / "input"
PROCESSED_DIR = DATA_DIR / "processed"
ARCHIVE_DIR = DATA_DIR / "archive"

OUTPUTS_DIR = BASE_DIR / "outputs"
REPORTS_DIR = OUTPUTS_DIR / "reports"
EXPORTS_DIR = OUTPUTS_DIR / "exports"
LOGS_DIR = OUTPUTS_DIR / "logs"

REPLICON_DIR = INPUT_DIR / "replicon"

# Pipeline searches INPUT_DIR for any file matching this glob at runtime.
SERVICENOW_FILENAME_PATTERN = "time_card*.xls*"

RESOURCES_FILE = INPUT_DIR / "Resources.xlsx"

# ── Sensitive values — loaded from .env (see .env.example) ────────────────────
# Sheet name inside Resources.xlsx that contains the roster.
RESOURCES_SHEET: str = os.getenv("RESOURCES_SHEET", "Resource List")

# JSON object: ServiceNow User ID → exact roster Name.
# Add an entry whenever someone's email-derived UID differs from their TC User ID.
UID_OVERRIDES: dict = json.loads(os.getenv("UID_OVERRIDES", "{}"))

# JSON array of first-name strings for members on reduced-hours arrangements.
# These members are Compliant if they log any hours at all (threshold does not apply).
PARTIAL_HOURS_EXCEPTIONS: list = json.loads(os.getenv("PARTIAL_HOURS_EXCEPTIONS", "[]"))
# FTE = hours / (40 * utilisation). Agreed utilisation rate with client.
UTILIZATION_RATE: float = float(os.getenv("UTILIZATION_RATE", "0.85"))
HOURS_PER_FTE: float = round(40 * UTILIZATION_RATE, 4)

# Target weekly FTE band for the Power BI in-band flag. JSON array [lower, upper].
FTE_BAND: tuple = tuple(json.loads(os.getenv("FTE_BAND", "[100, 119]")))

# Technology names from the time-card export mapped to Power BI report groups.
# JSON object loaded from .env so the client's tech stack is not in source control.
TECH_MAP: dict = json.loads(os.getenv("TECH_MAP", "{}"))# ──────────────────────────────────────────────────────────────────────────────

# If this file exists it overrides the auto-generated fuzzy matches.
# Export the auto-generated mapping, correct any wrong rows, save under
# this name, then re-run.
USER_MAPPING_APPROVED_FILENAME = "user_mapping_approved.xlsx"
USER_MAPPING_APPROVED_PATH = INPUT_DIR / USER_MAPPING_APPROVED_FILENAME

REFERENCE_GRAPH1_CSV = BASE_DIR.parent / "reference_graph1_with_gen.csv"
REFERENCE_GRAPH2_CSV = BASE_DIR.parent / "reference_graph2_no_gen.csv"

# score >= AUTO_ACCEPT: auto_accepted | [REVIEW_LOW, AUTO_ACCEPT): review_required | below: rejected
AUTO_ACCEPT_THRESHOLD: float = 0.80
REVIEW_LOW_THRESHOLD: float = 0.70

# compliant = >= 40 h/week; monthly = 5 full weeks x 40 h
HOURS_THRESHOLD_WEEKLY: int = 40
HOURS_THRESHOLD_MONTHLY: int = 200

# Graph 2 (no-GEN) counts Task work and Sick/Holiday as billable task hours.
TASK_CATEGORIES: list = ["Task work", "Sick/Holiday"]

TIMESTAMP: str = datetime.now().strftime("%Y%m%d_%H%M%S")

def output_path(filename: str, subdir: Path | None = None) -> Path:
    """Return a full output path, creating the parent directory if needed."""
    base = subdir if subdir is not None else REPORTS_DIR
    base.mkdir(parents=True, exist_ok=True)
    return base / filename

for _d in (REPORTS_DIR, EXPORTS_DIR, LOGS_DIR, INPUT_DIR, PROCESSED_DIR, ARCHIVE_DIR):
    _d.mkdir(parents=True, exist_ok=True)
