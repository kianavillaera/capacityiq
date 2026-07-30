#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# daily_pipeline.sh
#
# Triggered by Windows Task Scheduler (hourly) via the PowerShell wrapper.
# Power Automate already saves attachments to SharePoint at:
#   Managed Services/Extracts/{YYYY-MM-DD}/Time card (SNow)/
#
# This script:
# 1. Scans the OneDrive-synced Extracts folder for any new dated subfolders.
# 2. Copies new "IQ Time card*.xls*" files to the pipeline input folder.
# 3. Runs the daily (weekly-attendance) compliance pipeline.
# 4. Copies the output report back to the SharePoint outputs folder.
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

PIPELINE_DIR="/home/mabdelhameed2/CIQ/reporting_pipeline"
PYTHON="/home/mabdelhameed2/CIQ/.venv/bin/python"
INPUT_DIR="$PIPELINE_DIR/data/input"
STATE_FILE="$PIPELINE_DIR/automation/.processed_files"
LOG_FILE="$PIPELINE_DIR/automation/daily_pipeline.log"

# ── UPDATE THIS after syncing SharePoint via OneDrive ─────────────────────────
# Navigate to: https://kpmgoneuk.sharepoint.com/sites/GB-DataScienceTeams
# Open "Shared Documents" → "Managed Services" → click Sync in the toolbar.
# OneDrive will show you the local path — paste it below (Windows path).
# Typical format: C:\Users\mabdelhameed2\KPMG UK\GB-DataScienceTeams - Documents
# ─────────────────────────────────────────────────────────────────────────────
SHAREPOINT_SYNC_ROOT="/mnt/c/Users/mabdelhameed2/KPMG/GB - Data Science - KPMG MBS - Documents"

EXTRACTS_DIR="$SHAREPOINT_SYNC_ROOT/Managed Services/Extracts"
SHAREPOINT_REPORTS="$SHAREPOINT_SYNC_ROOT/Managed Services/Time card reports"

mkdir -p "$SHAREPOINT_REPORTS"
touch "$STATE_FILE"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"; }

log "=== Daily pipeline check ==="

# ── Scan all dated subfolders for new time card files ─────────────────────────
NEW_FILES=()
while IFS= read -r -d '' f; do
    fname=$(basename "$f")
    # folder_date = the YYYY-MM-DD part of the path
    folder_date=$(basename "$(dirname "$(dirname "$f")")")  # e.g. 2026-07-28
    # Skip files not inside a dated folder
    [[ "$folder_date" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] || continue
    key="${folder_date}/${fname}"
    if ! grep -qF "$key" "$STATE_FILE" 2>/dev/null; then
        NEW_FILES+=("$f")
    fi
done < <(find "$EXTRACTS_DIR" -maxdepth 3 -iname "IQ Time card*.xls*" -print0 2>/dev/null)

if [[ ${#NEW_FILES[@]} -eq 0 ]]; then
    log "No new files found. Exiting."
    exit 0
fi

# ── Copy new files to input with time_card_ prefix ───────────────────────────
for f in "${NEW_FILES[@]}"; do
    fname=$(basename "$f")
    folder_date=$(basename "$(dirname "$(dirname "$f")")")  # e.g. 2026-07-28
    safe=$(echo "${folder_date}_${fname}" | sed 's/IQ Time card data - //I; s/ /_/g; s/[^A-Za-z0-9._-]//g')
    dest="$INPUT_DIR/time_card_${safe}"
    cp "$f" "$dest"
    echo "${folder_date}/${fname}" >> "$STATE_FILE"
    log "Copied: $folder_date/$fname → time_card_${safe}"
done

# ── Run daily compliance pipeline ────────────────────────────────────────────
log "Running daily compliance pipeline..."
cd "$PIPELINE_DIR"

$PYTHON -c "
import sys; sys.path.insert(0, '.')
import pandas as pd
from config import settings
from src.utils import setup_logging
from src.pipeline import run_weekly_attendance_pipeline

setup_logging(settings.LOGS_DIR)

# Use the two most recently modified time_card files
latest = sorted(
    [f for f in settings.INPUT_DIR.glob('time_card*.xls*') if ':' not in f.name],
    key=lambda f: f.stat().st_mtime, reverse=True
)[:2]

result = run_weekly_attendance_pipeline(
    timecard_paths=latest,
    resources_path=settings.RESOURCES_FILE,
    output_dir=settings.REPORTS_DIR,
    resources_sheet=settings.RESOURCES_SHEET,
    hours_threshold=settings.HOURS_THRESHOLD_WEEKLY,
    timestamp=settings.TIMESTAMP,
)
print(result['output_path'])
" 2>&1 | tee -a "$LOG_FILE"

# ── Copy report to SharePoint ─────────────────────────────────────────────────
REPORT_DATE=$(date '+%Y-%m-%d')
mkdir -p "$SHAREPOINT_REPORTS"

LATEST_REPORT=$(ls -t "$PIPELINE_DIR/outputs/reports/compliance_2026-"*.xlsx 2>/dev/null | head -1)
if [[ -n "$LATEST_REPORT" ]]; then
    cp "$LATEST_REPORT" "$SHAREPOINT_REPORTS/compliance_daily_${REPORT_DATE}.xlsx"
    log "Saved to SharePoint: $SHAREPOINT_REPORTS/compliance_daily_${REPORT_DATE}.xlsx"
fi

log "=== Daily pipeline complete ==="
