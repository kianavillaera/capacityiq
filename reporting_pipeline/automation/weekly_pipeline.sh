#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# weekly_pipeline.sh
#
# Triggered by Windows Task Scheduler every Monday at 08:00.
# Power Automate already saves attachments to SharePoint at:
#   Managed Services/Extracts/{YYYY-MM-DD}/Time card (SNow)/
#
# This script:
# 1. Copies ALL unprocessed files from all dated subfolders to pipeline input.
# 2. Runs the FTE pipeline (full history from 2024).
# 3. Merges with historical timecard_data to include any gap weeks.
# 4. Runs monthly compliance (Jun–present) + weekly compliance (latest week).
# 5. Copies all three reports back to SharePoint.
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

PIPELINE_DIR="/home/mabdelhameed2/CIQ/reporting_pipeline"
PYTHON="/home/mabdelhameed2/CIQ/.venv/bin/python"
INPUT_DIR="$PIPELINE_DIR/data/input"
STATE_FILE="$PIPELINE_DIR/automation/.processed_files"
LOG_FILE="$PIPELINE_DIR/automation/weekly_pipeline.log"

# ── UPDATE THIS after syncing SharePoint via OneDrive ─────────────────────────
SHAREPOINT_SYNC_ROOT="/mnt/c/Users/mabdelhameed2/KPMG/GB - Data Science - KPMG MBS - Documents"

EXTRACTS_DIR="$SHAREPOINT_SYNC_ROOT/Managed Services/Extracts"
SHAREPOINT_REPORTS="$SHAREPOINT_SYNC_ROOT/Managed Services/Time card reports"

mkdir -p "$SHAREPOINT_REPORTS"
touch "$STATE_FILE"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"; }

log "=== Weekly/Monthly pipeline ==="

# ── Copy all unprocessed time card files from all dated subfolders ─────────────
while IFS= read -r -d '' f; do
    fname=$(basename "$f")
    folder_date=$(basename "$(dirname "$(dirname "$f")")")  # e.g. 2026-07-28
    # Skip files not inside a dated folder
    [[ "$folder_date" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] || continue
    key="${folder_date}/${fname}"
    if ! grep -qF "$key" "$STATE_FILE" 2>/dev/null; then
        safe=$(echo "${folder_date}_${fname}" | sed 's/IQ Time card data - //I; s/ /_/g; s/[^A-Za-z0-9._-]//g')
        dest="$INPUT_DIR/time_card_${safe}"
        cp "$f" "$dest"
        echo "$key" >> "$STATE_FILE"
        log "Copied: $key → time_card_${safe}"
    fi
done < <(find "$EXTRACTS_DIR" -maxdepth 3 -iname "IQ Time card*.xls*" -print0 2>/dev/null)

cd "$PIPELINE_DIR"

# ── Step 1: FTE pipeline ──────────────────────────────────────────────────────
log "Running FTE pipeline..."
$PYTHON main.py --fte 2>&1 | tee -a "$LOG_FILE"

# ── Step 2: Merge with historical timecard_data (fills gap weeks) ─────────────
log "Merging with historical data..."
$PYTHON -c "
import sys; sys.path.insert(0, '.')
import pandas as pd
from pathlib import Path
from config import settings

old_tc = Path('/home/mabdelhameed2/CIQ/output/timecard_data.xlsx')
new_tc = sorted(settings.EXPORTS_DIR.glob('timecard_data_[0-9]*.xlsx'))[-1]

df_old = pd.read_excel(old_tc, sheet_name='with_gen')
df_new = pd.read_excel(new_tc, sheet_name='with_gen')
df_old['_src'] = 'old'; df_new['_src'] = 'new'
combined = pd.concat([df_old, df_new], ignore_index=True)

meta = [c for c in ('_source_file','_src','_sheet','week_start','is_gen') if c in combined.columns]
combined = combined.drop_duplicates(
    subset=[c for c in combined.columns if c not in meta], keep='last'
).reset_index(drop=True)

merged_path = settings.EXPORTS_DIR / f'timecard_data_merged_{settings.TIMESTAMP}.xlsx'
combined.drop(columns=[c for c in meta if c in combined.columns]).to_excel(
    merged_path, sheet_name='with_gen', index=False
)
print(merged_path)
" 2>&1 | tee -a "$LOG_FILE"

# ── Step 3: Monthly + weekly compliance ──────────────────────────────────────
log "Running monthly and weekly compliance..."
$PYTHON -c "
import sys; sys.path.insert(0, '.')
import pandas as pd
from pathlib import Path
from datetime import date
from config import settings
from src.utils import setup_logging
from src.pipeline import run_monthly_attendance_pipeline, run_weekly_attendance_pipeline

setup_logging(settings.LOGS_DIR)

merged_path = sorted(settings.EXPORTS_DIR.glob('timecard_data_merged_*.xlsx'))[-1]

m = run_monthly_attendance_pipeline(
    timecard_data_path=merged_path,
    resources_path=settings.RESOURCES_FILE,
    month_start=pd.Timestamp('2026-06-01'),
    month_end=pd.Timestamp(date.today()),
    month_label='June-July 2026',
    output_dir=settings.REPORTS_DIR,
    resources_sheet=settings.RESOURCES_SHEET,
    hours_threshold=settings.HOURS_THRESHOLD_WEEKLY,
    month_threshold=settings.HOURS_THRESHOLD_MONTHLY,
    timestamp=settings.TIMESTAMP,
)
print('Monthly:', m['output_path'])

latest = sorted(
    [f for f in settings.INPUT_DIR.glob('time_card*.xls*') if ':' not in f.name],
    key=lambda f: f.stat().st_mtime, reverse=True
)[:2]
w = run_weekly_attendance_pipeline(
    timecard_paths=latest,
    resources_path=settings.RESOURCES_FILE,
    output_dir=settings.REPORTS_DIR,
    resources_sheet=settings.RESOURCES_SHEET,
    hours_threshold=settings.HOURS_THRESHOLD_WEEKLY,
    timestamp=settings.TIMESTAMP,
)
print('Weekly:', w['output_path'])
" 2>&1 | tee -a "$LOG_FILE"

# ── Step 4: Copy all three reports to SharePoint ──────────────────────────────
REPORT_DATE=$(date '+%Y-%m-%d')
mkdir -p "$SHAREPOINT_REPORTS"

cp "$(ls -t outputs/exports/powerbi_fte_weekly_*.xlsx | head -1)" \
   "$SHAREPOINT_REPORTS/powerbi_fte_weekly_${REPORT_DATE}.xlsx" && log "Saved FTE report"

cp "$(ls -t outputs/reports/compliance_June*.xlsx | head -1)" \
   "$SHAREPOINT_REPORTS/compliance_June-July_2026_${REPORT_DATE}.xlsx" && log "Saved monthly compliance"

cp "$(ls -t outputs/reports/compliance_2026-*.xlsx | head -1)" \
   "$SHAREPOINT_REPORTS/compliance_weekly_${REPORT_DATE}.xlsx" && log "Saved weekly compliance"

log "=== Weekly/Monthly pipeline complete ==="
