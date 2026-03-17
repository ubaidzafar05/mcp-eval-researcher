PYTHON ?= python
PYTHONPATH ?= $(PWD)/src
export PYTHONPATH

.PHONY: test lint export-requirements check-requirements preflight compose-validate smoke-local dev-up dev-up-balanced dev-up-full dev-down dev-ui dev dev-smoke
.PHONY: clean-artifacts clean-caches

test:
	$(PYTHON) -m pytest -q -m "not stress"

lint:
	$(PYTHON) -m ruff check .

export-requirements:
	$(PYTHON) -m scripts.export_requirements requirements.txt full

check-requirements:
	$(PYTHON) -m scripts.check_requirements_sync

preflight:
	$(PYTHON) -m scripts.preflight_git_identity

compose-validate:
	docker compose config

smoke-local:
	$(PYTHON) -m scripts.local_stack_smoke

dev-up:
	docker compose --profile core up -d web-mcp-http local-mcp-http app

dev-up-balanced:
	docker compose --profile core --profile distributed up -d web-mcp-http local-mcp-http redis celery-worker app

dev-up-full:
	docker compose --profile core --profile distributed --profile observability up -d web-mcp-http local-mcp-http redis celery-worker app prometheus grafana jaeger

dev-down:
	docker compose down

dev-ui:
	cd web-ui && npm run dev

# One command for day-to-day local development:
# 1) bring backend stack up in Docker
# 2) start UI dev server in foreground
dev: dev-up
	cd web-ui && npm run dev

# Quick backend quality smoke (deep-research path with strict provenance)
dev-smoke:
	$(PYTHON) -m scripts.provider_smoke_minimal

# Move ad-hoc / redirected logs out of repo root.
clean-artifacts:
	@mkdir -p logs/legacy
	@ts="$$(date +%Y%m%d-%H%M%S)"; \
	for f in *.log *.log.*; do \
		if [ -f "$$f" ]; then \
			dest="logs/legacy/$$f"; \
			if [ -e "$$dest" ]; then dest="logs/legacy/$${f}.$$ts"; fi; \
			mv "$$f" "$$dest"; \
		fi; \
	done; \
	if [ -f "web-ui/ui_local.log" ]; then \
		dest="logs/legacy/ui_local.log"; \
		if [ -e "$$dest" ]; then dest="logs/legacy/ui_local.log.$$ts"; fi; \
		mv "web-ui/ui_local.log" "$$dest"; \
	fi

# Optional: remove local caches to keep the tree clean.
clean-caches:
	@rm -rf .pytest_cache .ruff_cache .mypy_cache __pycache__
	@find . -type d -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null || true
