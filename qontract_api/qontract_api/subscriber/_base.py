# ruff: noqa: RUF029
from typing import Any

from faststream.asgi import AsgiFastStream, AsgiResponse, get, make_ping_asgi
from faststream.redis import RedisBroker
from faststream.redis.prometheus import RedisPrometheusMiddleware
from faststream.specification import AsyncAPI
from prometheus_client import CollectorRegistry, make_asgi_app

from qontract_api.config import settings

if settings.cache_backend != "redis":
    raise RuntimeError(
        "Event publishing is only supported with Redis backend. Subscriber cannot be started."
    )

registry = CollectorRegistry()
broker = RedisBroker(
    settings.cache_broker_url,
    middlewares=[RedisPrometheusMiddleware(registry=registry)],
)


@get
async def liveness_ping(*_: Any) -> AsgiResponse:
    return AsgiResponse(b"", status_code=200)


app = AsgiFastStream(
    broker,
    specification=AsyncAPI(),
    asyncapi_path="/docs/asyncapi",
    asgi_routes=[
        ("/health/ready", make_ping_asgi(broker, timeout=5.0)),
        ("/health/live", liveness_ping),
        ("/metrics", make_asgi_app(registry)),
    ],
)
