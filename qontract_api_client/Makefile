OPENAPI := ../qontract_api/openapi.json
OUTPUT_DIR := qontract_api_client

.PHONY: help
help:
	@echo "qontract-api-client Makefile"
	@echo ""
	@echo "Development:"
	@echo "  make generate-client 	Generate API client from Qontract API OpenAPI spec"
	@echo ""
	@echo "Quality:"
	@echo "  make test              Run all checks (pytest, mypy, ruff)"
	@echo "  make format            Format and fix code with ruff"


.PHONY: generate-client
generate-client:
	clientele start-api -f $(OPENAPI) -o $(OUTPUT_DIR) --asyncio --regen
	@rm -f $(OUTPUT_DIR)/pyproject.toml $(OUTPUT_DIR)/MANIFEST.md
	@$(MAKE) format OUTPUT_DIR=$(OUTPUT_DIR)

.PHONY: test
test:
	@TEMP_DIR=$$(mktemp -d); \
	trap "rm -rf $$TEMP_DIR" EXIT; \
	$(MAKE) generate-client OUTPUT_DIR=$$TEMP_DIR/qontract_api_client; \
	if ! diff -r -q qontract_api_client $$TEMP_DIR/qontract_api_client > /dev/null 2>&1; then \
		echo "  ✗ Client differs from generated version"; \
		echo ""; \
		echo "Run 'make generate-client' to update."; \
		echo ""; \
		exit 1; \
	fi
	@uv run ruff check .
	@uv run ruff format --check .
	@uv run mypy .
	@uv run pytest --cov=qontract_api_client --cov-report=term-missing --cov-report xml

.PHONY: format
format:
	uv run ruff check --fix $(OUTPUT_DIR)
	uv run ruff format $(OUTPUT_DIR)

.PHONY: pypi
pypi:
	uv build --sdist --wheel --out-dir dist
	uv publish || true
