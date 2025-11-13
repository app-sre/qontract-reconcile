# qontract-api

REST API service for qontract reconciliation.

## Quick Start

Start the full stack with Docker Compose:

```bash
docker compose up
```

Services:

- API: <http://localhost:8000>
- API Docs: <http://localhost:8000/docs>
- Cache (Redis): localhost:6379

## Architecture

The API is built using:

- **FastAPI** - Modern async web framework
- **Celery** - Distributed task queue
- **Redis/Valkey** - Cache and message broker
- **Pydantic** - Data validation
- **uv** - Fast Python package manager

### Project Structure

```
qontract_api/
├── qontract_api/
│   ├── main.py           # FastAPI application
│   ├── config.py         # Pydantic settings
│   └── tasks/
│       ├── __init__.py   # Celery app
│       └── health.py     # Health check task
├── Dockerfile            # Multi-stage Docker build
├── app.sh               # Entrypoint script
└── pyproject.toml       # Package metadata
```

## Development

### Prerequisites

- Python 3.12+
- [uv](https://github.com/astral-sh/uv) package manager
- Docker and Docker Compose (for containerized development)

### Setup

```bash
# From repository root
uv sync --all-packages

# From qontract_api directory
cd qontract_api
make help
```

### Running Locally

```bash
# API server
make run-api

# Celery worker
make run-worker

# Both (requires Redis running)
make run-dev
```

### Docker Development

```bash
# Start all services
docker compose up

# Rebuild images
docker compose build

# View logs
docker compose logs -f api
docker compose logs -f celery-worker

# Stop all services
docker compose down
```

### Environment Variables

Copy `.env.example` to `.env` and adjust values:

```bash
cp .env.example .env
```

Key variables:

- `QAPI_START_MODE` - Runtime mode: `api` or `worker`
- `QAPI_AUTO_RELOAD` - Enable auto-reload for development
- `CACHE_BROKER_URL` - Redis/Valkey connection URL
- `LOG_LEVEL` - Logging level (DEBUG, INFO, WARNING, ERROR)

## Testing

```bash
# Run tests
make test

# Run linter
make lint

# Run type checker
make types

# Run all checks
make check
```

## API Endpoints

- `GET /` - Root endpoint
- `GET /health` - Health check
- `GET /docs` - Interactive API documentation (Swagger UI)
- `GET /redoc` - Alternative API documentation (ReDoc)

## Celery Tasks

List registered tasks:

```python
from qontract_api.tasks import celery_app
print(celery_app.tasks.keys())
```

Execute health check task:

```python
from qontract_api.tasks.health import health_check
result = health_check.delay()
print(result.get())
```

## Documentation

- POC Plan: [../POC_PLAN.md](../POC_PLAN.md)
- Implementation Guide: [../POC_IMPLEMENTATION_GUIDE.md](../POC_IMPLEMENTATION_GUIDE.md)
