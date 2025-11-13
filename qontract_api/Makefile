.PHONY: help
help:
	@echo "qontract-api Makefile"
	@echo ""
	@echo "Development:"
	@echo "  make run-api       Run FastAPI server locally"
	@echo "  make run-worker    Run Celery worker locally"
	@echo "  make generate-token SUBJECT=<subject> DAYS=<days>"
	@echo "                     Generate JWT token (default: DAYS=30)"
	@echo ""
	@echo "Docker:"
	@echo "  make docker-up     Start all services"
	@echo "  make docker-down   Stop all services"
	@echo "  make docker-build  Rebuild images"
	@echo "  make docker-logs   View logs"
	@echo ""
	@echo "Quality:"
	@echo "  make test          Run all checks (pytest, mypy, ruff)"
	@echo "  make format        Format and fix code with ruff"
	@echo "  make clean         Remove build artifacts"

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
		echo "Usage: make generate-token SUBJECT=admin DAYS=30"; \
		exit 1; \
	fi
	@uv run python -m qontract_api.scripts.generate_token --username "$(SUBJECT)" --expires-days $(or $(DAYS),30)

.PHONY: docker-up
docker-up:
	cd .. && docker compose up

.PHONY: docker-down
docker-down:
	cd .. && docker compose down

.PHONY: docker-build
docker-build:
	cd .. && docker compose build

.PHONY: docker-logs
docker-logs:
	cd .. && docker compose logs -f

.PHONY: test
test:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy .
	uv run pytest

.PHONY: format
format:
	uv run ruff check --fix .
	uv run ruff format .

.PHONY: clean
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
