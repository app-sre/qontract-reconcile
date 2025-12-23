from prometheus_client import start_http_server
from prometheus_client.multiprocess import MultiProcessCollector

from qontract_api.config import settings

# import celery app to start the worker
from qontract_api.tasks import celery_app  # noqa: F401
from qontract_api.tasks.metrics import CELERY_REGISTRY

MultiProcessCollector(CELERY_REGISTRY)
start_http_server(port=settings.worker_metrics_port, registry=CELERY_REGISTRY)
