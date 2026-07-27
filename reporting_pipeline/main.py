#!/usr/bin/env python3
"""
Entry point for the reporting pipeline.

Usage:
    python main.py              # Interactive terminal menu
    python main.py --reconcile  # Run reconciliation pipeline directly
    python main.py --fte        # Run FTE data prep pipeline directly
    python main.py --attendance # Run weekly attendance pipeline directly
    python main.py --validate   # Validate inputs only
"""

import sys
import argparse
import logging
from pathlib import Path

# Ensure project root is on sys.path so imports work regardless of
# where the script is invoked from.
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import settings
from src.utils import setup_logging
from src.pipeline import (
    run_reconciliation_pipeline,
    run_fte_pipeline,
    run_weekly_attendance_pipeline,
    run_validation_only,
)

logger = logging.getLogger(__name__)

def _menu() -> None:
    """Interactive terminal menu for business users."""
    print()
    print("=" * 60)
    print("  📊  Reporting Pipeline")
    print("=" * 60)
    print()
    print("  [1]  Run full reconciliation pipeline")
    print("  [2]  Run FTE data prep (Power BI)")
    print("  [3]  Run weekly attendance analysis")
    print("  [4]  Validate inputs only")
    print("  [5]  Launch Streamlit application")
    print("  [0]  Exit")
    print()

    choice = input("Enter choice: ").strip()

    if choice == "1":
        _run_reconciliation()
    elif choice == "2":
        _run_fte()
    elif choice == "3":
        _run_weekly_attendance()
    elif choice == "4":
        _run_validate()
    elif choice == "5":
        _launch_streamlit()
    elif choice == "0":
        print("Goodbye.")
        sys.exit(0)
    else:
        print("Invalid choice. Please try again.")
        _menu()

def _run_reconciliation() -> None:
    print()
    timecard_paths = _find_timecard_files()
    if not timecard_paths:
        logger.error("No time-card files found in %s.", settings.INPUT_DIR)
        return
    try:
        results = run_reconciliation_pipeline(
            replicon_dir=settings.REPLICON_DIR,
            timecard_paths=timecard_paths,
            output_dir=settings.REPORTS_DIR,
            approved_mapping_path=settings.USER_MAPPING_APPROVED_PATH,
            auto_accept=settings.AUTO_ACCEPT_THRESHOLD,
            review_low=settings.REVIEW_LOW_THRESHOLD,
            timestamp=settings.TIMESTAMP,
        )
        print()
        for label, path in results.get("output_paths", {}).items():
            print(f"  {label}: {path}")
    except Exception as exc:
        logger.error("Reconciliation failed: %s", exc, exc_info=True)

def _run_fte() -> None:
    timecard_paths = _find_timecard_files()
    if not timecard_paths:
        logger.error("No time-card files found in %s.", settings.INPUT_DIR)
        return
    try:
        results = run_fte_pipeline(
            timecard_paths=timecard_paths,
            output_dir=settings.EXPORTS_DIR,
            ref_graph1_path=settings.REFERENCE_GRAPH1_CSV if settings.REFERENCE_GRAPH1_CSV.exists() else None,
            ref_graph2_path=settings.REFERENCE_GRAPH2_CSV if settings.REFERENCE_GRAPH2_CSV.exists() else None,
            timestamp=settings.TIMESTAMP,
        )
        print()
        for label, path in results.get("output_paths", {}).items():
            print(f"  {label}: {path}")
    except Exception as exc:
        logger.error("FTE pipeline failed: %s", exc, exc_info=True)

def _run_weekly_attendance() -> None:
    timecard_paths = _find_timecard_files()
    if not timecard_paths:
        logger.error("No time-card files found in %s.", settings.INPUT_DIR)
        return
    if not settings.RESOURCES_FILE.exists():
        logger.error("Resources.xlsx not found in %s.", settings.INPUT_DIR)
        return
    try:
        results = run_weekly_attendance_pipeline(
            timecard_paths=timecard_paths,
            resources_path=settings.RESOURCES_FILE,
            output_dir=settings.REPORTS_DIR,
            resources_sheet=settings.RESOURCES_SHEET,
            hours_threshold=settings.HOURS_THRESHOLD_WEEKLY,
            timestamp=settings.TIMESTAMP,
        )
        print(f"\n  Report: {results['output_path']}")
    except Exception as exc:
        logger.error("Attendance pipeline failed: %s", exc, exc_info=True)

def _run_validate() -> None:
    approved = settings.USER_MAPPING_APPROVED_PATH if settings.USER_MAPPING_APPROVED_PATH.exists() else None
    passed = run_validation_only(
        replicon_dir=settings.REPLICON_DIR,
        timecard_paths=_find_timecard_files(),
        approved_mapping_path=approved,
    )
    print("  All checks passed." if passed else "  Validation failed - see log above.")

def _launch_streamlit() -> None:
    import subprocess
    app_path = PROJECT_ROOT / "app" / "streamlit_app.py"
    print(f"\nLaunching Streamlit: {app_path}")
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(app_path)])

def _find_timecard_files() -> list[Path]:
    """Find all time-card files in the input directory."""
    return sorted(
        p for p in settings.INPUT_DIR.glob(settings.SERVICENOW_FILENAME_PATTERN)
        if ":" not in p.name
    )

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Reporting pipeline.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--reconcile",  action="store_true")
    group.add_argument("--fte",         action="store_true")
    group.add_argument("--attendance",  action="store_true")
    group.add_argument("--validate",    action="store_true")
    group.add_argument("--streamlit",   action="store_true")
    return parser.parse_args()

def main() -> None:
    args = _parse_args()
    setup_logging(log_dir=settings.LOGS_DIR)

    if args.reconcile:  _run_reconciliation()
    elif args.fte:       _run_fte()
    elif args.attendance: _run_weekly_attendance()
    elif args.validate:  _run_validate()
    elif args.streamlit: _launch_streamlit()
    else:                _menu()

if __name__ == "__main__":
    main()
