import logging
import os
import threading
from collections.abc import Mapping
from typing import (
    Any,
    Optional,
)

from UnleashClient import (
    BaseCache,
    UnleashClient,
)
from UnleashClient.strategies import Strategy

client: Optional[UnleashClient] = None
client_lock = threading.Lock()


class CacheDict(BaseCache):
    def __init__(self):
        self.cache = {}

    def set(self, key: str, value: Any):
        self.cache[key] = value

    def mset(self, data: dict):
        self.cache.update(data)

    def get(self, key: str, default: Optional[Any] = None):
        return self.cache.get(key, default)

    def exists(self, key: str):
        return key in self.cache

    def destroy(self):
        self.cache = {}


class ClusterStrategy(Strategy):
    def load_provisioning(self) -> list:
        return [x.strip() for x in self.parameters["cluster_name"].split(",")]


class DisableClusterStrategy(ClusterStrategy):
    def apply(self, context: Optional[dict] = None) -> bool:
        enable = True

        if context and "cluster_name" in context.keys():
            # if cluster in context is in clusters sent from server, disable
            enable = context["cluster_name"] not in self.parsed_provisioning

        return enable


class EnableClusterStrategy(ClusterStrategy):
    def apply(self, context: Optional[dict] = None) -> bool:
        enable = False

        if context and "cluster_name" in context.keys():
            # if cluster in context is in clusters sent from server, enable
            enable = context["cluster_name"] in self.parsed_provisioning

        return enable


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
                    "enableCluster": EnableClusterStrategy,
                    "disableCluster": DisableClusterStrategy,
                },
            )
            client.initialize_client()
    return client


def _shutdown_client():
    # Intended for test usage only
    with client_lock:
        if client:
            client.destroy()


def get_feature_toggle_default(feature_name, context):
    return True


def get_feature_toggle_default_false(feature_name, context):
    return False


def get_feature_toggle_state(
    integration_name: str, context: Optional[dict] = None, default: bool = True
) -> bool:
    api_url = os.environ.get("UNLEASH_API_URL")
    client_access_token = os.environ.get("UNLEASH_CLIENT_ACCESS_TOKEN")
    if not (api_url and client_access_token):
        return get_feature_toggle_default(None, None)

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


def get_feature_toggles(api_url: str, client_access_token: str) -> Mapping[str, str]:
    c = _get_unleash_api_client(api_url, client_access_token)

    return {k: "enabled" if v.enabled else "disabled" for k, v in c.features.items()}
