PYTHON ?= python

.PHONY: test lint export-requirements check-requirements preflight

test:
	$(PYTHON) -m pytest -q -m "not stress"

lint:
	$(PYTHON) -m ruff check .

export-requirements:
	$(PYTHON) -m scripts.export_requirements

check-requirements:
	$(PYTHON) -m scripts.check_requirements_sync

preflight:
	$(PYTHON) -m scripts.preflight_git_identity

