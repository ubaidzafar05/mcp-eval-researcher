PYTHON ?= python

.PHONY: test lint export-requirements check-requirements preflight compose-validate smoke-local

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

compose-validate:
	docker compose config

smoke-local:
	$(PYTHON) -m scripts.local_stack_smoke
