#!/usr/bin/env python3
"""
Quality check runner.

Runs all quality gates in sequence and prints a summary:
  - Syntax check (all src modules)
  - Import check (all src modules)
  - Unit + BDD tests with coverage
  - Coverage threshold assertion
  - Mutation testing summary (if mutmut available)

Usage:
    python tests/run_quality_check.py
    python tests/run_quality_check.py --no-mutation   # skip mutation (slow)
"""

import ast
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

PYTHON = sys.executable
SRC_FILES = sorted((PROJECT_ROOT / "src").glob("*.py"))


def section(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print("=" * 60)


def run(cmd: list, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


# ---------------------------------------------------------------------------
# 1. Syntax check
# ---------------------------------------------------------------------------
section("1. Syntax check")
syntax_ok = True
for f in SRC_FILES:
    try:
        ast.parse(f.read_text())
        print(f"  OK  {f.name}")
    except SyntaxError as e:
        print(f"  ERR {f.name}: line {e.lineno} - {e.msg}")
        syntax_ok = False

if not syntax_ok:
    print("\nAborting: syntax errors found.")
    sys.exit(1)


# ---------------------------------------------------------------------------
# 2. Import check
# ---------------------------------------------------------------------------
section("2. Import check")
import_ok = True
modules = [
    "config.settings",
    "src.utils",
    "src.loaders",
    "src.validators",
    "src.transformations",
    "src.mappings",
    "src.reconciliation",
    "src.exporters",
    "src.fte_prep",
    "src.report_generator",
    "src.pipeline",
]
for m in modules:
    try:
        __import__(m)
        print(f"  OK  {m}")
    except ImportError as e:
        print(f"  ERR {m}: {e}")
        import_ok = False

if not import_ok:
    print("\nAborting: import errors found.")
    sys.exit(1)


# ---------------------------------------------------------------------------
# 3. Tests + coverage
# ---------------------------------------------------------------------------
section("3. Unit tests + BDD tests + coverage")
result = run(
    [
        PYTHON,
        "-m",
        "pytest",
        "tests/",
        "--cov=src",
        "--cov-report=term-missing",
        "--cov-report=html:outputs/coverage_html",
        "--cov-fail-under=70",
        "-v",
        "--tb=short",
    ],
    cwd=PROJECT_ROOT,
)

print(result.stdout)
if result.returncode != 0:
    print(result.stderr)
    print("\nTests or coverage threshold failed.")
    sys.exit(1)


# ---------------------------------------------------------------------------
# 4. Extract coverage metrics
# ---------------------------------------------------------------------------
section("4. Coverage summary")
lines = result.stdout.splitlines()
for line in lines:
    if "TOTAL" in line or "%" in line and "src/" in line:
        print(f"  {line.strip()}")

cov_line = next((line for line in lines if "TOTAL" in line), None)
if cov_line:
    try:
        pct = int(cov_line.split()[-1].replace("%", ""))
        status = "PASS" if pct >= 70 else "FAIL"
        print(f"\n  Coverage: {pct}%  [{status}]")
    except (ValueError, IndexError):
        pass


# ---------------------------------------------------------------------------
# 5. Mutation testing (optional, slow)
# ---------------------------------------------------------------------------
skip_mutation = "--no-mutation" in sys.argv
section("5. Mutation testing (mutmut)")
if skip_mutation:
    print("  Skipped (pass --no-mutation to skip).")
else:
    print("  Running mutmut on src/reconciliation.py and src/mappings.py...")
    print("  (This may take several minutes.)")
    mut = run(
        [
            PYTHON,
            "-m",
            "mutmut",
            "run",
            "--paths-to-mutate",
            "src/reconciliation.py,src/mappings.py",
            "--tests-dir",
            "tests/",
        ],
        cwd=PROJECT_ROOT,
        timeout=300,
    )
    print(mut.stdout[-3000:] if len(mut.stdout) > 3000 else mut.stdout)

    results_proc = run([PYTHON, "-m", "mutmut", "results"], cwd=PROJECT_ROOT)
    print(results_proc.stdout)


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
section("Summary")
print("  Syntax check  : PASS")
print("  Import check  : PASS")
print("  Tests         : PASS")
print("  Coverage      : >= 70%")
if not skip_mutation:
    print("  Mutation      : see results above")
print()
print("  All quality gates passed.")
