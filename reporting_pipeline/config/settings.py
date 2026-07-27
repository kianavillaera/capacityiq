"""Central configuration -- paths, thresholds, and constants."""

from pathlib import Path
from datetime import datetime

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
RESOURCES_SHEET = "Resource List 20250206"

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

# FTE = hours / (40 * utilisation). 34 h/week per FTE at 85% utilisation.
UTILIZATION_RATE: float = 0.85
HOURS_PER_FTE: float = round(40 * UTILIZATION_RATE, 4)
FTE_BAND: tuple = (100, 119)

# Technology names from the time-card export mapped to Power BI report groups.
TECH_MAP: dict = {
    "Dynamics 365 FO": "F&O",
    "Dynamics 365 FSCM": "F&O",
    "Dynamics 365 CE": "CE",
    "Dynamics 365 BC": "BC",
    "Dynamics NAV": "BC",
    "Microsoft Azure": "Azure Integ",
    "Microsoft Cloud Data Warehouse": "Inf Mgmt",
    "Microsoft Cloud Support Infrastructure": "Inf Mgmt",
    "Power Platform": "Power Platform",
}

# Graph 2 (no-GEN) counts Task work and Sick/Holiday as billable task hours.
TASK_CATEGORIES: list = ["Task work", "Sick/Holiday"]

# Manual overrides for users whose time-card UID does not match their roster entry.
UID_OVERRIDES: dict = {
    "amitkumar.singh": "Singh, Amit Kumar",
    "sravan.boini": "Kumar, Boini Sravan",
}

TIMESTAMP: str = datetime.now().strftime("%Y%m%d_%H%M%S")

def output_path(filename: str, subdir: Path | None = None) -> Path:
    """Return a full output path, creating the parent directory if needed."""
    base = subdir if subdir is not None else REPORTS_DIR
    base.mkdir(parents=True, exist_ok=True)
    return base / filename

for _d in (REPORTS_DIR, EXPORTS_DIR, LOGS_DIR, INPUT_DIR, PROCESSED_DIR, ARCHIVE_DIR):
    _d.mkdir(parents=True, exist_ok=True)
