import logging
import os
import threading
from typing import Any

from UnleashClient import (
    BaseCache,
    UnleashClient,
)

client: UnleashClient | None = None
client_lock = threading.Lock()


class CacheDict(BaseCache):
    def __init__(self) -> None:
        self.cache: dict = {}

    def set(self, key: str, value: Any) -> None:
        self.cache[key] = value

    def mset(self, data: dict) -> None:
        self.cache.update(data)

    def get(self, key: str, default: Any | None = None) -> Any:
        return self.cache.get(key, default)

    def exists(self, key: str) -> bool:
        return key in self.cache

    def destroy(self) -> None:
        self.cache = {}


def _parse_cluster_names(parameters: dict) -> list[str]:
    return [x.strip() for x in parameters["cluster_name"].split(",")]


class DisableClusterStrategy:
    def apply(self, parameters: dict, context: dict | None = None) -> bool:
        if context and "cluster_name" in context:
            return context["cluster_name"] not in _parse_cluster_names(parameters)
        return True


class EnableClusterStrategy:
    def apply(self, parameters: dict, context: dict | None = None) -> bool:
        if context and "cluster_name" in context:
            return context["cluster_name"] in _parse_cluster_names(parameters)
        return False


def _get_unleash_api_client(api_url: str, auth_head: str) -> UnleashClient:
    global client  # noqa: PLW0603
    with client_lock:
        if client is None:
            logging.getLogger("apscheduler").setLevel(logging.ERROR)
            logging.getLogger("UnleashClient").setLevel(logging.ERROR)
            headers = {"Authorization": auth_head}
            client = UnleashClient(
                url=api_url,
                app_name="qontract-reconcile",
                custom_headers=headers,
                cache=CacheDict(),
                custom_strategies={
                    "enableCluster": EnableClusterStrategy(),
                    "disableCluster": DisableClusterStrategy(),
                },
            )
            client.initialize_client()
    return client


def get_feature_toggle_default(feature_name: str, context: dict) -> bool:
    return True


def get_feature_toggle_default_false(feature_name: str, context: dict) -> bool:
    return False


def get_feature_toggle_state(
    integration_name: str, context: dict | None = None, default: bool = True
) -> bool:
    api_url = os.environ.get("UNLEASH_API_URL")
    client_access_token = os.environ.get("UNLEASH_CLIENT_ACCESS_TOKEN")
    if not (api_url and client_access_token):
        return get_feature_toggle_default("", {})

    c = _get_unleash_api_client(
        api_url,
        client_access_token,
    )

    fallback_func = (
        get_feature_toggle_default if default else get_feature_toggle_default_false
    )

    return c.is_enabled(
        integration_name,
        context=context,
        fallback_function=fallback_func,
    )


def get_feature_variant(
    feature_name: str, context: dict | None = None, default_variant: str = ""
) -> str:
    """Return the variant payload value for a feature toggle.

    If Unleash is unavailable or the toggle has no variant configured,
    returns *default_variant*.
    """
    api_url = os.environ.get("UNLEASH_API_URL")
    client_access_token = os.environ.get("UNLEASH_CLIENT_ACCESS_TOKEN")
    if not (api_url and client_access_token):
        return default_variant

    c = _get_unleash_api_client(api_url, client_access_token)
    variant = c.get_variant(feature_name, context=context or {})
    if variant and variant.get("enabled"):
        payload = variant.get("payload", {})
        if payload:
            return payload.get("value", default_variant)
    return default_variant
