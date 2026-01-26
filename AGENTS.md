# AGENTS.md

## Project Overview

**qontract-reconcile** is a comprehensive infrastructure reconciliation tool developed by Red Hat's App-SRE Team. It manages 80+ integrations across AWS, OpenShift, GitHub, GitLab, and other platforms, following a declarative "desired state vs current state" reconciliation pattern.

## Development Environment

### Prerequisites

- **Python 3.12**
- **uv** for dependency management (modern pip/pipenv replacement)
- **Docker** for containerized development

### Setup

```bash
uv sync -U               # Install dependencies
```

## Essential Commands

### Code Quality

```bash
make format              # Format code with ruff
make linter-test         # Run linting checks
make types-test          # Run MyPy type checking
```

### Testing

```bash
make unittest            # Run unit tests
make all-tests           # Run full test suite (unit + integration)
pytest path/to/test.py   # Run specific test file
pytest -k "test_name"    # Run tests matching pattern
```

### Development Workflows

```bash
make gql-query-classes   # Regenerate GraphQL dataclasses (required after schema changes)
make dev-reconcile-loop  # Start containerized development environment
```

## Architecture Overview

### Core Reconciliation Pattern

1. **Fetch desired state** from App-Interface GraphQL API
2. **Discover current state** from target systems (AWS, OpenShift, etc.)
3. **Calculate diff** between desired and current state
4. **Apply changes** to reconcile the difference

### Key Directories

- `reconcile/` - 158 integration modules + core utilities
- `reconcile/gql_definitions/` - Auto-generated GraphQL dataclasses (do not edit manually)
- `qontract-api/` - REST API server for our integrations
- `qontract-api-client/` - Auto-generated Python client for qontract-api
- `qontract-utils/` - Utilities shared across qontract-api and reconcile
- `tools/` - CLI utilities and standalone tools
- `docs/patterns/` - Architectural documentation and best practices
- `docs/ADR/` - Architectural decision records

### GraphQL Data Binding

- Uses `qenerate` to generate type-safe Python dataclasses from GraphQL schemas
- All data fetching uses generated Pydantic models for type safety
- Schema changes require running `make gql-query-classes`

### Integration Structure

Most integrations follow this pattern:

```python
def run(dry_run: bool, thread_pool_size: int = 10) -> None:
    """Main entry point for integration"""
    # 1. Fetch desired state from GraphQL
    # 2. Discover current state from target system
    # 3. Calculate diffs
    # 4. Apply changes (unless dry_run=True)
```

## Testing Guidelines

### Test Organization

- Unit tests: `tests/` directory, mirror the source structure
- Integration tests: Use pytest fixtures for external dependencies
- All tests must pass for CI/CD pipeline

### Test Utilities

- `reconcile.test.fixtures` - Common test fixtures and utilities
- Comprehensive mocking support for external API calls
- Use `@pytest.fixture` for reusable test data

## Common Development Patterns

### Error Handling

- Use structured logging with `reconcile.utils.logger`
- Implement proper exception handling for external API calls
- Support for signal handling and graceful shutdowns

### Configuration

- Environment-based configuration via `reconcile.utils.config`
- Support for both file-based and environment variable configuration
- Vault integration for sensitive data

### Sharding Support

- Many integrations support horizontal scaling via sharding
- Use `reconcile.utils.sharding` utilities
- Test both sharded and non-sharded execution paths

### Archtitectural Decisions

- Documented in `docs/ADR/` directory
- Follow the decisions for consistency across integrations
- Always choose the "Selected" in the Alternatives Considered section
- Treat the examples as examples, don't follow them blindly. You're allowed to adapt them to the current context and needs.

## Integration Development

### Creating New Integrations

1. Create module in `reconcile/` directory
2. Implement `run()` function with `dry_run` parameter
3. Add comprehensive unit tests
4. Update GraphQL queries if needed (run `make gql-query-classes`)
5. Add integration to appropriate configuration

### GraphQL Queries

- Define queries in integration modules
- Use type-safe generated classes from `reconcile.gql_definitions`
- Regenerate classes after schema changes: `make gql-query-classes`

## Debugging and Development

### Local Development

- Use `make dev-reconcile-loop` for containerized development
- Environment variables in `.env` files for local configuration
- Comprehensive dry-run support for safe testing

### Profiling and Monitoring

- Built-in profiling support via `reconcile.utils.profiling`
- Prometheus metrics integration
- Structured logging with correlation IDs

## Important Notes

- **Never edit** files in `reconcile/gql_definitions/**/*.py` - they are auto-generated
- Always test integrations in dry-run mode first
- Use type hints consistently - MyPy enforcement is strict
- Follow existing patterns for error handling and logging
- All public functions should include comprehensive docstrings
