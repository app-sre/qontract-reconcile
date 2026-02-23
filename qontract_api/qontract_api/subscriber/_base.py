# ruff: noqa: RUF029
from typing import Any

from faststream.asgi import AsgiFastStream, AsgiResponse, get, make_ping_asgi
from faststream.redis import RedisBroker
from faststream.specification import AsyncAPI

from qontract_api.config import settings

if not settings.events.enabled:
    raise RuntimeError("Event publishing is disabled. Subscriber cannot be started.")
if settings.cache_backend != "redis":
    raise RuntimeError(
        "Event publishing is only supported with Redis backend. Subscriber cannot be started."
    )

broker = RedisBroker(settings.cache_broker_url)


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
    ],
)
