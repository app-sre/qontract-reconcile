OPENAPI := openapi.json

.PHONY: help
help:
	@echo "qontract-api Makefile"
	@echo ""
	@echo "Development:"
	@echo "  make run-api                                                Run FastAPI server locally"
	@echo "  make run-worker                                             Run Celery worker locally"
	@echo "  make generate-token SUBJECT=<subject> EXPIRES_DAYS=<days>   Generate JWT token"
	@echo "  make generate-openapi-spec                                  Generate OpenAPI spec file"
	@echo ""
	@echo "Quality:"
	@echo "  make test                                                   Run all checks (pytest, mypy, ruff)"
	@echo "  make format                                                 Format and fix code with ruff"

.PHONY: run-api
run-api:
	uv run uvicorn qontract_api.main:app --host 0.0.0.0 --port 8000 --reload

.PHONY: run-worker
run-worker:
	uv run celery --app=qontract_api.tasks worker --loglevel=info

.PHONY: generate-token
generate-token:
	@if [ -z "$(SUBJECT)" ]; then \
		echo "Error: SUBJECT is required"; \
		echo "Usage: make generate-token SUBJECT=admin EXPIRES_DAYS=365"; \
		exit 1; \
	fi
	@if [ -z "$(EXPIRES_DAYS)" ]; then \
		echo "Error: SUBJECT is required"; \
		echo "Usage: make generate-token SUBJECT=admin EXPIRES_DAYS=365"; \
		exit 1; \
	fi
	@uv run python -m qontract_api.scripts.generate_token --subject "$(SUBJECT)" --expires-days "$(EXPIRES_DAYS)"

.PHONY: generate-openapi-spec
generate-openapi-spec:
	@uv run python -m qontract_api.scripts.generate_openapi_spec > $(OPENAPI)

.PHONY: test
test: generate-openapi-spec
	git diff --exit-code $(OPENAPI)
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy .
	uv run pytest --cov=qontract_api --cov-report=term-missing --cov-report xml

.PHONY: format
format:
	uv run ruff check --fix .
	uv run ruff format .
