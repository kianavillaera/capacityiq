# Reporting Pipeline

A production-ready Python pipeline for timesheet reconciliation and attendance analysis across Replicon and ServiceNow.

---

## Overview

This pipeline provides three main reporting workflows:

| Pipeline | Purpose |
|---|---|
| **Reconciliation** | Compare Replicon and ServiceNow time records at `date × user × task_code` grain and produce a variance report |
| **FTE Data Prep** | Aggregate time-card data into weekly FTE metrics for Power BI |
| **Attendance Analysis** | Generate weekly and monthly attendance compliance reports from the resource roster |

---

## Project Structure

```
reporting_pipeline/
├── app/
│   └── streamlit_app.py       # Streamlit web interface
├── config/
│   └── settings.py            # All configurable paths, thresholds, and constants
├── data/
│   ├── input/                 # Place your input files here
│   │   └── replicon/          # Replicon CSV/XLSX exports (one or more)
│   ├── processed/             # Intermediate files
│   └── archive/               # Archived inputs
├── outputs/
│   ├── reports/               # Generated Excel reports
│   ├── exports/               # Power BI / data exports
│   └── logs/                  # Pipeline execution logs
├── src/
│   ├── loaders.py             # Data loading functions
│   ├── validators.py          # Input validation
│   ├── transformations.py     # Data cleaning and type coercion
│   ├── mappings.py            # Name normalisation and user matching
│   ├── reconciliation.py      # Core reconciliation engine
│   ├── report_generator.py    # Attendance report building and styling
│   ├── fte_prep.py            # FTE aggregation for Power BI
│   ├── exporters.py           # Excel export functions
│   ├── pipeline.py            # End-to-end pipeline orchestrators
│   └── utils.py               # Logging and timing utilities
├── tests/                     # Test suite
├── notebooks/                 # Exploratory notebooks (not production)
├── main.py                    # Entry point (interactive menu + CLI flags)
├── requirements.txt
├── README.md
└── REFACTOR_SUMMARY.md
```

---

## Installation

```bash
# 1. Clone or copy the project
cd reporting_pipeline

# 2. Create and activate a virtual environment (recommended)
python -m venv .venv
source .venv/bin/activate        # Linux / macOS
# .venv\Scripts\activate         # Windows

# 3. Install dependencies
pip install -r requirements.txt
```

---

## Dependencies

| Package | Purpose |
|---|---|
| `pandas` | Data manipulation |
| `openpyxl` | Excel read/write (.xlsx) |
| `xlrd` | Legacy Excel read (.xls) |
| `streamlit` | Web interface |
| `numpy` | Numeric operations |
| `jellyfish` | Jaro-Winkler fuzzy name matching |
| `rapidfuzz` | Token-sort / token-set fuzzy matching |
| `pytest` | Test runner |

`jellyfish` and `rapidfuzz` are optional but strongly recommended for accurate user matching.

---

## How to Run

### Interactive menu

```bash
cd reporting_pipeline
python main.py
```

This launches a numbered menu:

```
[1]  Run full reconciliation pipeline
[2]  Run FTE data prep (Power BI)
[3]  Run weekly attendance analysis
[4]  Validate inputs only
[5]  Launch Streamlit application
[0]  Exit
```

### CLI flags (non-interactive)

```bash
python main.py --reconcile     # Reconciliation only
python main.py --fte           # FTE data prep only
python main.py --attendance    # Weekly attendance only
python main.py --validate      # Validate inputs only
python main.py --streamlit     # Launch Streamlit
```

### Streamlit application

```bash
streamlit run app/streamlit_app.py
```

---

## Expected Input Files

### Reconciliation pipeline

| File | Location | Format | Notes |
|---|---|---|---|
| Replicon extracts | `data/input/replicon/` | CSV or XLSX | One or more monthly Diary Notes exports |
| ServiceNow time card | `data/input/` | XLS or XLSX | Any file matching `time_card*.xls*` |
| Approved user mapping | `data/input/user_mapping_approved.xlsx` | XLSX | Optional; generated on first run |

### FTE / Attendance pipelines

| File | Location | Format | Notes |
|---|---|---|---|
| Time card files | `data/input/` | XLS or XLSX | Any file matching `time_card*.xls*` |
| Resource roster | `data/input/Resources.xlsx` | XLSX | Sheet: `Resource List 20250206` |

---

## Required Columns

### Replicon extract

| Column | Notes |
|---|---|
| `Entry Date` | Format: `DD.MM.YYYY` |
| `User Name` | May be merged-cell style (forward-filled automatically) |
| `Task Code` | Required for reconciliation |
| `Employee ID` | Optional |
| `Project Code` | Optional |
| `Hours` or `Hours Worked` | Blank treated as 0 (business rule) |

### ServiceNow time card

| Column | Notes |
|---|---|
| `Date` | Any parseable date format |
| `User` | Display name |
| `User ID` | Login / email prefix |
| `Project ID` | Task code |
| `Time worked` | Numeric hours |

---

## Output Locations

| Output | Location | Naming |
|---|---|---|
| Reconciliation workbook | `outputs/reports/` | `reconciliation_YYYYMMDD_HHMMSS.xlsx` |
| Exception report | `outputs/reports/` | `exception_report_YYYYMMDD_HHMMSS.xlsx` |
| User mapping | `outputs/reports/` | `user_mapping_YYYYMMDD_HHMMSS.xlsx` |
| Summary | `outputs/reports/` | `summary_YYYYMMDD_HHMMSS.xlsx` |
| Power BI FTE workbook | `outputs/exports/` | `powerbi_fte_weekly_YYYYMMDD_HHMMSS.xlsx` |
| Timecard data | `outputs/exports/` | `timecard_data_YYYYMMDD_HHMMSS.xlsx` |
| Attendance report | `outputs/reports/` | `attendance_YYYY-MM-DD_YYYYMMDD_HHMMSS.xlsx` |
| Logs | `outputs/logs/` | `pipeline_YYYYMMDD_HHMMSS.log` |

---

## User Matching Workflow

1. The pipeline automatically matches Replicon users to ServiceNow users using exact name, exact UID, and fuzzy scoring.
2. Matches scoring above `AUTO_ACCEPT_THRESHOLD` (default: 0.80) are auto-accepted.
3. Matches between `REVIEW_LOW_THRESHOLD` (0.70) and the auto-accept threshold are flagged for review.
4. After the first run, download `user_mapping_*.xlsx` from `outputs/reports/`, review any flagged rows, correct the `servicenow_user_id` column, set `match_status = auto_accepted`, and save as `data/input/user_mapping_approved.xlsx`.
5. On subsequent runs, the approved mapping is loaded automatically.

---

## Assumptions

- Replicon dates are in `DD.MM.YYYY` format.
- Blank Replicon hours are treated as 0 (submitted entries with no hours logged).
- On-call time-card rows (`Rate type` contains "On-Call") are excluded from attendance totals but reported separately.
- The reconciliation grain is `date × user × task_code`.
- ServiceNow data is scoped to the Replicon date window, matched users, and matching task codes before reconciliation.
- Weekly FTE is calculated as total hours / (40 × 0.85) = hours / 34.
- The expected FTE band is 100–119 (Graph 1, all hours including GEN).

---

## Troubleshooting

| Symptom | Likely cause | Resolution |
|---|---|---|
| "No CSV or XLSX files found" | Replicon files not placed in correct folder | Place files in `data/input/replicon/` |
| "No usable rows after cleaning" | Date format wrong | Ensure Replicon export uses `DD.MM.YYYY` for Entry Date |
| Many users flagged for review | Names differ significantly between systems | Review and correct `user_mapping_approved.xlsx` |
| Hours do not tieout | Duplicate rows in source data | Check for and remove duplicate records before running |
| `jellyfish` / `rapidfuzz` not found | Libraries not installed | Run `pip install jellyfish rapidfuzz` |

---

## Running Tests

```bash
cd reporting_pipeline
pytest tests/ -v
```

---

## Configuration

Edit `config/settings.py` to change:

- Input/output directory paths
- Matching thresholds (`AUTO_ACCEPT_THRESHOLD`, `REVIEW_LOW_THRESHOLD`)
- Attendance thresholds (`HOURS_THRESHOLD_WEEKLY`, `HOURS_THRESHOLD_MONTHLY`)
- FTE parameters (`UTILIZATION_RATE`, `FTE_BAND`)
- Technology group mappings (`TECH_MAP`)
- Known UID overrides (`UID_OVERRIDES`)
