# Timesheet Reconciliation

Reconciles hours between Replicon and ServiceNow for invoicing validation.

Grain: `date × user × task_code` | Variance = `SN hours − Replicon hours`

---

## Prerequisites

```bash
cd /home/mabdelhameed2/CIQ
source .venv/bin/activate
pip install pandas openpyxl jellyfish rapidfuzz streamlit
```

---

## Run the Streamlit app (recommended)

```bash
cd /home/mabdelhameed2/CIQ
source .venv/bin/activate
streamlit run app.py
```

Open `http://localhost:8501` in your browser.

**Steps in the UI:**

1. Upload Replicon CSV(s) and the ServiceNow Excel in the sidebar
2. Adjust matching thresholds if needed (defaults: auto-accept ≥ 0.80, review floor ≥ 0.70)
3. Review the data quality cards for each source
4. Confirm or fix any flagged user matches before the pipeline proceeds
5. Download outputs from the bottom of the page

**To fix a wrong user match:**

1. Download `user_mapping_review_*.xlsx` from the review gate
2. Set `match_status = auto_accepted` and correct `servicenow_user_id` for the affected rows
3. Re-upload the file in the UI — the pipeline re-runs automatically

---

## Run the notebook (batch / scripted)

```bash
cd /home/mabdelhameed2/CIQ
source .venv/bin/activate
jupyter notebook reconciliation.ipynb
```

Edit `REPLICON_FILES` and `SERVICENOW_FILE` in cell 3 before running.

To lock in a reviewed user mapping, save your corrected file as `user_mapping_approved.xlsx`
in the project root. The notebook loads it automatically on the next run.

Output files are written to `output/` with a timestamp suffix.

---

## Files

| File | Purpose |
|---|---|
| `app.py` | Streamlit frontend |
| `reconciliation.py` | All pipeline logic (importable, no UI) |
| `reconciliation.ipynb` | Batch notebook — thin wrapper over `reconciliation.py` |
| `user_mapping_approved.xlsx` | Optional: manually reviewed user mapping |
| `output/` | Timestamped output files |

---

## Output files

| File | Contents |
|---|---|
| `reconciliation_*.xlsx` | Sheets: `detail`, `by_user`, one per month |
| `exception_report_*.xlsx` | Rows with discrepancies or missing data |
| `user_mapping_*.xlsx` | Full user matching table with scores |
| `summary_*.xlsx` | Run metrics |

---

## Monthly rerun

1. Add the new Replicon CSV path to `REPLICON_FILES` (notebook) or upload it in the sidebar (app)
2. Replace the ServiceNow file if a new extract is available
3. Re-run — outputs are timestamped and previous files are not overwritten
