PYTHON := /home/mabdelhameed2/CIQ/.venv/bin/python
PIP    := /home/mabdelhameed2/CIQ/.venv/bin/pip

.PHONY: check check-slow inspect report-check

check:
	@echo "── format ──────────────────────────────────────────────────────"
	$(PYTHON) -m ruff format --check src/ tests/
	@echo "── lint ────────────────────────────────────────────────────────"
	$(PYTHON) -m ruff check src/ tests/
	@echo "── types ───────────────────────────────────────────────────────"
	$(PYTHON) -m mypy src/ --ignore-missing-imports --no-error-summary
	@echo "── dead code ───────────────────────────────────────────────────"
	$(PYTHON) -m vulture src/ whitelist_vulture.py --min-confidence 80
	@echo "── tests ───────────────────────────────────────────────────────"
	$(PYTHON) -m pytest tests/unit/ tests/step_defs/ tests/test_contracts.py \
	    tests/test_golden.py tests/test_determinism.py \
	    -p randomly --randomly-seed=12345 -q --tb=short
	@echo "── check complete ──────────────────────────────────────────────"

check-slow: check
	@echo "── mutation testing ────────────────────────────────────────────"
	$(PYTHON) -m mutmut run --no-progress
	$(PYTHON) -m mutmut results
	@echo "── check-slow complete ─────────────────────────────────────────"

inspect:
	$(PYTHON) tests/run_quality_check.py $(RUN)

report-check:
	$(PYTHON) tests/run_report_check.py $(REPORT)
