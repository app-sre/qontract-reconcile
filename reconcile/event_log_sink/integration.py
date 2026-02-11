import logging

from qontract_utils.events.factory import create_event_consumer
from redis import Redis

from reconcile.utils.jinja2.filters import urlescape
from reconcile.utils.runtime.integration import (
    PydanticRunParams,
    QontractReconcileIntegration,
)
from reconcile.utils.semver_helper import make_semver

QONTRACT_INTEGRATION = "event-log-sink"
QONTRACT_INTEGRATION_VERSION = make_semver(1, 0, 0)


class EventLogSinkParams(PydanticRunParams):
    redis_url_secret_path: str | None = None
    redis_url: str | None = None
    redis_ssl: bool = True
    stream_key: str = "qontract:events"
    consumer_group: str = "event-log-sink"
    consumer_name: str = "default"


def exteral_resource_secret_to_redis_url(secret: dict[str, str], ssl: bool) -> str:
    """Compose a Redis URL from the given external resources secret data."""
    protocol = "rediss" if ssl else "redis"
    auth_part = ""
    if "db.auth_token" in secret:
        auth_part = f":{urlescape(secret['db.auth_token'], safe='')}@"

    return f"{protocol}://{auth_part}{secret['db.endpoint']}:{secret['db.port']}/0?ssl_cert_reqs=required"


class EventLogSinkIntegration(
    QontractReconcileIntegration[EventLogSinkParams],
):
    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    def run(self, dry_run: bool) -> None:
        if not self.params.redis_url and not self.params.redis_url_secret_path:
            raise RuntimeError(
                "Either redis_url or redis_url_secret_path must be provided"
            )
        if self.params.redis_url_secret_path:
            redis_secret = self.secret_reader.read_all({
                "path": self.params.redis_url_secret_path,
            })
            redis_url = exteral_resource_secret_to_redis_url(
                redis_secret, self.params.redis_ssl
            )
        elif self.params.redis_url:
            redis_url = self.params.redis_url

        client = Redis.from_url(redis_url, encoding="utf-8", decode_responses=True)

        try:
            consumer = create_event_consumer(
                "redis",
                client=client,
                stream_key=self.params.stream_key,
                consumer_group=self.params.consumer_group,
                consumer_name=self.params.consumer_name,
            )

            while True:
                events = consumer.receive(block=True, acknowledge=not dry_run)

                if not events:
                    continue

                for _message_id, event in events:
                    logging.info(
                        f"type={event.event_type} source={event.source} payload={event.payload}"
                    )
        finally:
            client.close()
