PYTHON ?= python3

.PHONY: check test-gates ci list eval-plan eval release hooks clean

check:
	$(PYTHON) scripts/check.py --all

test-gates:
	$(PYTHON) scripts/test_gates.py

ci: check test-gates

list:
	$(PYTHON) scripts/check.py --list

eval-plan:
	$(PYTHON) scripts/run_evals.py --plan

eval:
	$(PYTHON) scripts/run_evals.py --run

release: check
	$(PYTHON) scripts/release.py --all

hooks:
	git config core.hooksPath .githooks
	chmod +x .githooks/pre-commit

clean:
	rm -rf dist __pycache__ scripts/__pycache__
