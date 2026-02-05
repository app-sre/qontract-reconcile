.PHONY: help
help:
	@echo "qontract-utils Makefile"
	@echo ""
	@echo "Quality:"
	@echo "  make test          Run all checks (pytest, mypy, ruff)"
	@echo "  make format        Format and fix code with ruff"


.PHONY: test
test:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy .
	uv run pytest --cov=qontract_utils --cov-report=term-missing --cov-report xml

.PHONY: format
format:
	uv run ruff check --fix .
	uv run ruff format .

.PHONY: pypi
pypi:
	uv build --sdist --wheel --out-dir dist
	uv publish || true
