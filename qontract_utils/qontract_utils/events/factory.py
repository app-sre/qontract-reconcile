from __future__ import annotations

from typing import TYPE_CHECKING

from qontract_utils.events.redis_streams import (
    RedisStreamsEventConsumer,
    RedisStreamsEventPublisher,
)

if TYPE_CHECKING:
    from redis import Redis

    from qontract_utils.events.protocols import EventConsumer, EventPublisher


def create_event_publisher(
    backend: str,
    *,
    # redis kwargs
    client: Redis | None = None,
    stream_key: str = "",
) -> EventPublisher:
    """Create an event publisher for the given backend.

    Args:
        backend: Backend type ("redis" or "sns")
        client: Redis client (required for "redis" backend)
        stream_key: Redis Stream key (required for "redis" backend)
        aws_api: AWS API instance (required for "sns" backend)
        topic_arn: SNS topic ARN (required for "sns" backend)

    Returns:
        EventPublisher implementation
    """
    match backend:
        case "redis":
            assert client is not None, (
                "Redis client is required for Redis event publisher"
            )
            return RedisStreamsEventPublisher(client=client, stream_key=stream_key)
        case _:
            raise ValueError(f"Unknown event publisher backend: {backend}")


def create_event_consumer(
    backend: str,
    *,
    # redis kwargs
    client: Redis | None = None,
    stream_key: str = "",
    consumer_group: str = "",
    consumer_name: str = "",
) -> EventConsumer:
    """Create an event consumer for the given backend.

    Args:
        backend: Backend type ("redis" or "sqs")
        client: Redis client (required for "redis" backend)
        stream_key: Redis Stream key (required for "redis" backend)
        consumer_group: Consumer group name (required for "redis" backend)
        consumer_name: Consumer name (required for "redis" backend)

    Returns:
        EventConsumer implementation
    """
    match backend:
        case "redis":
            assert client is not None, (
                "Redis client is required for Redis event consumer"
            )
            return RedisStreamsEventConsumer(
                client=client,
                stream_key=stream_key,
                consumer_group=consumer_group,
                consumer_name=consumer_name,
            )
        case _:
            raise ValueError(f"Unknown event consumer backend: {backend}")
