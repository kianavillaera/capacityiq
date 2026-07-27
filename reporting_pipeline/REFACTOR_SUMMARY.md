# Refactor Summary

## Original Project Structure

```
/CIQ/
├── app.py                              # Streamlit UI (monolithic — mixed UI + business logic)
├── reconciliation.py                   # Core library (loaders, cleaners, matching, engine)
├── _build_nb.py                        # Script to generate reconciliation.ipynb from code
├── reconciliation.ipynb                # Notebook wrapper of reconciliation.py
├── attendance_analysis.ipynb           # Weekly attendance analysis (self-contained)
├── attendance_analysis_june2026.ipynb  # Monthly attendance analysis (depends on FTE output)
├── powerbi_fte_data_prep.ipynb         # FTE aggregation for Power BI (self-contained)
├── ciq.ipynb                           # Exploratory / legacy
├── ciq_executed.ipynb                  # Executed copy of ciq.ipynb
├── discrepancy_report.ipynb            # Exploratory / legacy
├── l.ipynb                             # Scratch notebook
├── test.ipynb                          # Scratch notebook
├── data/                               # Raw data files
└── output/                             # Unstructured output folder
```

## New Project Structure

```
reporting_pipeline/
├── app/
│   └── streamlit_app.py               # Streamlit UI (UI only — all logic in src/)
├── config/
│   ├── __init__.py
│   └── settings.py                    # All configurable values in one place
├── data/
│   ├── input/
│   │   └── replicon/                  # Replicon extracts go here
│   ├── processed/
│   └── archive/
├── outputs/
│   ├── reports/                       # Excel reports
│   ├── exports/                       # Power BI / data exports
│   └── logs/                          # Rotating log files
├── src/
│   ├── __init__.py
│   ├── loaders.py                     # All data loading functions
│   ├── validators.py                  # Input validation and error raising
│   ├── transformations.py             # Cleaning, type coercion, derived columns
│   ├── mappings.py                    # Name normalisation + user matching
│   ├── reconciliation.py              # Core reconciliation engine
│   ├── report_generator.py            # Attendance report building and Excel styling
│   ├── fte_prep.py                    # FTE aggregation for Power BI
│   ├── exporters.py                   # All Excel export functions
│   ├── pipeline.py                    # End-to-end pipeline orchestrators
│   └── utils.py                       # Logging setup and timer context manager
├── tests/
│   ├── __init__.py
│   ├── test_loaders.py
│   ├── test_validators.py
│   ├── test_transformations.py
│   ├── test_mappings.py
│   └── test_reconciliation.py
├── notebooks/
│   └── (exploratory notebooks can be placed here)
├── main.py                            # Entry point: interactive menu + CLI flags
├── requirements.txt
├── README.md
└── REFACTOR_SUMMARY.md
```

---

## Files Added

| File | Purpose |
|---|---|
| `config/settings.py` | Centralised configuration (paths, thresholds, constants) |
| `src/__init__.py` | Package marker |
| `src/loaders.py` | Extracted and extended loader functions |
| `src/validators.py` | New validation layer with clear error messages |
| `src/transformations.py` | Extracted and documented cleaning functions |
| `src/mappings.py` | Extracted name normalisation and user matching |
| `src/reconciliation.py` | Production reconciliation engine |
| `src/report_generator.py` | Extracted attendance report building and styling |
| `src/fte_prep.py` | Extracted Power BI FTE aggregation logic |
| `src/exporters.py` | Extracted all export functions |
| `src/pipeline.py` | New orchestrators for each end-to-end workflow |
| `src/utils.py` | Logging setup and timer context manager |
| `app/streamlit_app.py` | Refactored Streamlit app (UI only) |
| `main.py` | New entry point with interactive menu and CLI flags |
| `tests/test_loaders.py` | Loader tests |
| `tests/test_validators.py` | Validator tests |
| `tests/test_transformations.py` | Transformation tests |
| `tests/test_mappings.py` | Mapping / normalisation tests |
| `tests/test_reconciliation.py` | Reconciliation engine tests |
| `requirements.txt` | Clean, minimal dependency list |
| `README.md` | Comprehensive project documentation |

---

## Files Removed / Not Carried Forward

| File | Reason |
|---|---|
| `_build_nb.py` | Build script for generating a notebook from code — obsolete; the notebook is no longer the primary artefact |
| `reconciliation.ipynb` | Superseded by `src/reconciliation.py` + `src/pipeline.py`; kept as exploratory notebook template in `notebooks/` if needed |
| `ciq.ipynb` | Legacy / exploratory only |
| `ciq_executed.ipynb` | Executed output of legacy notebook |
| `discrepancy_report.ipynb` | Exploratory / superseded by exception report in reconciliation pipeline |
| `l.ipynb`, `test.ipynb` | Scratch notebooks |

**Note:** `attendance_analysis.ipynb`, `attendance_analysis_june2026.ipynb`, and `powerbi_fte_data_prep.ipynb` have been fully refactored into production modules but are retained in the original location as reference notebooks.

---

## Files Merged

| Source files | Destination | Notes |
|---|---|---|
| `reconciliation.py` (load_replicon_dir, load_timecard_files) | `src/loaders.py` | Extended with byte-stream variants for Streamlit |
| `reconciliation.py` (clean_replicon, clean_servicenow) | `src/transformations.py` | Added docstrings and logging |
| `reconciliation.py` (normalise_name, normalise_uid, build_user_mapping, match_users) | `src/mappings.py` | Unchanged logic, added docstrings |
| `reconciliation.py` (run, classify_exception, to_excel_bytes) + `app.py` (cached wrappers) | `src/reconciliation.py` + `src/exporters.py` | Separated engine from export |
| `attendance_analysis.ipynb` | `src/report_generator.py` + `src/pipeline.py` | Weekly attendance logic extracted |
| `attendance_analysis_june2026.ipynb` | `src/report_generator.py` + `src/pipeline.py` | Monthly attendance logic extracted |
| `powerbi_fte_data_prep.ipynb` | `src/fte_prep.py` + `src/exporters.py` + `src/pipeline.py` | FTE logic extracted |

---

## Major Refactoring Decisions

### 1. Separation of concerns
The original `reconciliation.py` mixed data loading, cleaning, matching, and reconciliation into one file. These are now split by responsibility across `loaders.py`, `transformations.py`, `mappings.py`, `reconciliation.py`, and `exporters.py`.

### 2. Notebook logic extracted to production modules
All business logic from the three analysis notebooks was extracted verbatim into `src/` modules. The notebooks themselves are no longer the execution path — they can be retained as exploratory references.

### 3. Centralised configuration
All hardcoded paths, thresholds, and constants were moved to `config/settings.py`. The pipeline modules import from there. Input/output directories are created automatically on first import.

### 4. Validation layer
A new `validators.py` module provides upfront validation before any processing occurs. Errors are raised with clear, actionable messages explaining exactly what is wrong and how to fix it.

### 5. Pipeline orchestrators
`src/pipeline.py` provides four orchestrators (`run_reconciliation_pipeline`, `run_fte_pipeline`, `run_weekly_attendance_pipeline`, `run_monthly_attendance_pipeline`) that wire together all the modules into end-to-end workflows with structured logging and timing.

### 6. Streamlit app decoupled from business logic
The original `app.py` embedded loading and cleaning logic directly. The new `app/streamlit_app.py` delegates all logic to `src/` modules and is pure UI code.

### 7. Structured logging throughout
All modules use Python's `logging` module. The `utils.py` module provides a `setup_logging()` function that configures both console and rotating file handlers. A `timer()` context manager logs execution time for each pipeline stage.

---

## Assumptions Made

- The `reconciliation.py` library in the original project was stable and well-tested — its logic was carried forward without modification.
- The Replicon `DD.MM.YYYY` date format is intentional and non-negotiable (business rule preserved).
- Blank Replicon hours → 0 is an intentional business rule (preserved).
- On-call rows excluded from attendance totals is intentional (preserved).
- The FTE calculation `hours / (40 × 0.85)` is correct and unchanged.
- The fuzzy matching weight formula (35% JW + 30% token-sort + 35% token-set) is intentional.
- The `UID_OVERRIDES` dict is a known exception list that should remain in configuration.

---

## Remaining Technical Debt

1. **Monthly attendance pipeline** — The `run_monthly_attendance_pipeline` requires the FTE pipeline output (`timecard_data.xlsx`) as its input, creating an implicit dependency. A future improvement would be to make it optionally accept raw time-card files directly.

2. **Plotly visualisations** — The FTE notebook includes interactive Plotly charts. These are not included in the production pipeline (they are not exportable to Excel). If charts are needed in production, a dedicated visualisation module or Streamlit FTE page should be added.

3. **Exploratory notebooks** — The original notebooks remain in the root of the workspace as reference. They should be moved to `notebooks/` and stripped of absolute hardcoded paths.

4. **Archive pipeline** — The `data/archive/` directory exists but no archiving logic has been implemented. A future improvement would be to move processed input files to archive after a successful run.

5. **Test coverage** — The test suite covers core units. Integration tests covering full end-to-end pipelines with real-ish fixture data would further increase confidence.

6. **Monthly attendance — date scoping** — The monthly pipeline currently applies date filtering inline. A dedicated transformer for date scoping would make this more explicit.

---

## Recommendations for Future Improvements

- Add a `run_pipeline.py` convenience script that chains all three pipelines in order (FTE first, then monthly attendance, then reconciliation).
- Add a Power BI-ready Streamlit tab for the FTE charts.
- Add file archiving to the pipeline (move processed inputs to `data/archive/`).
- Replace the absolute path in `attendance_analysis.ipynb` with relative imports from `config/settings.py` to make the notebook portable.
- Add integration tests using small fixture data files.
- Consider adding a CI workflow (GitHub Actions) to run tests on push.

---

## Architecture

```
Input Files (Replicon CSVs, ServiceNow XLSX, Resources XLSX)
      │
      ▼
Loaders  (src/loaders.py)
      │
      ▼
Validators  (src/validators.py)
      │
      ▼
Transformations  (src/transformations.py)
      │
      ▼
Mappings / User Matching  (src/mappings.py)
      │
      ▼
Reconciliation Engine  (src/reconciliation.py)
  ─── or ───
FTE Aggregation  (src/fte_prep.py)
  ─── or ───
Attendance Analysis  (src/report_generator.py)
      │
      ▼
Exporters  (src/exporters.py)
      │
      ▼
Outputs (outputs/reports/, outputs/exports/, outputs/logs/)
```

**Orchestration:**  `src/pipeline.py` → `main.py` (CLI) or `app/streamlit_app.py` (web)
