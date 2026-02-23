# ruff: noqa: RUF029
from qontract_utils.events import Event

from ._base import broker


@broker.subscriber("main")
async def base_handler(event: Event) -> None:
    print(event)
    print(type(event.data))
