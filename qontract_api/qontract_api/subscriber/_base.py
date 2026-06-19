# ruff: noqa: RUF029
from typing import Any

import structlog
from faststream._internal.basic_types import AsyncFuncAny
from faststream.asgi import AsgiFastStream, AsgiResponse, get, make_ping_asgi
from faststream.message import StreamMessage
from faststream.middlewares import BaseMiddleware
from faststream.redis import RedisBroker
from faststream.redis.prometheus import RedisPrometheusMiddleware
from faststream.specification import AsyncAPI
from prometheus_client import CollectorRegistry, make_asgi_app

from qontract_api.config import settings
from qontract_api.logger import setup_logging

if settings.cache_backend != "redis":
    raise RuntimeError(
        "Event publishing is only supported with Redis backend. Subscriber cannot be started."
    )


def _unpack_extra(
    _logger: Any, _method_name: str, event_dict: structlog.types.EventDict
) -> structlog.types.EventDict:
    """Unpack FastStream's extra dict into individual structlog event keys."""
    extra = event_dict.pop("extra", None)
    if isinstance(extra, dict):
        event_dict.update(extra)
    return event_dict


class StructlogContextMiddleware(BaseMiddleware[Any, Any]):
    """Propagate structlog context from message headers.

    Analogous to @celery.signals.task_prerun.connect in tasks/__init__.py.
    Automatically binds structlog contextvars from publisher-provided headers
    (e.g. request_id) before each handler runs.
    """

    async def consume_scope(  # noqa: PLR6301
        self,
        call_next: AsyncFuncAny,
        msg: StreamMessage[Any],
    ) -> Any:
        """Bind structlog context from message headers before handler execution."""
        structlog.contextvars.clear_contextvars()
        if msg.headers:
            structlog.contextvars.bind_contextvars(**msg.headers)
        return await call_next(msg)


registry = CollectorRegistry()
log = setup_logging(extra_processors=[_unpack_extra])
broker = RedisBroker(
    settings.cache_broker_url,
    middlewares=[
        RedisPrometheusMiddleware(registry=registry),
        StructlogContextMiddleware,
    ],
    logger=log,
)


@get
async def liveness_ping(*_: Any) -> AsgiResponse:
    return AsgiResponse(b"", status_code=200)


app = AsgiFastStream(
    broker,
    logger=log,
    specification=AsyncAPI(),
    asyncapi_path="/docs/asyncapi",
    asgi_routes=[
        ("/health/ready", make_ping_asgi(broker, timeout=5.0)),
        ("/health/live", liveness_ping),
        ("/metrics", make_asgi_app(registry)),
    ],
)
