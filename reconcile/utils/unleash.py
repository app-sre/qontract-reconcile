import logging
import os
import threading
from typing import Mapping, Optional, Any

from UnleashClient import UnleashClient, BaseCache
from UnleashClient import strategies
from UnleashClient.strategies import Strategy


client: Optional[UnleashClient] = None
client_lock = threading.Lock()

custom_strategies = ["perCluster", "perClusterNamespace"]


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


def _get_unleash_api_client(api_url: str, auth_head: str) -> UnleashClient:
    global client
    with client_lock:
        if client is None:
            headers = {"Authorization": f"Bearer {auth_head}"}
            client = UnleashClient(
                url=api_url,
                app_name="qontract-reconcile",
                custom_headers=headers,
                cache=CacheDict(),
                custom_strategies={
                    name: strategies.Strategy for name in custom_strategies
                },
            )
            client.initialize_client()
        logging.getLogger("apscheduler.executors.default").setLevel(logging.ERROR)
        logging.getLogger("UnleashClient").setLevel(logging.ERROR)
    return client


def get_feature_toggle_default(feature_name, context):
    return True


def get_feature_toggle_state(integration_name: str) -> bool:
    api_url = os.environ.get("UNLEASH_API_URL")
    client_access_token = os.environ.get("UNLEASH_CLIENT_ACCESS_TOKEN")
    if not (api_url and client_access_token):
        return get_feature_toggle_default(None, None)

    c = _get_unleash_api_client(
        api_url,
        client_access_token,
    )

    return c.is_enabled(integration_name, fallback_function=get_feature_toggle_default)


def get_feature_toggles(api_url: str, client_access_token: str) -> Mapping[str, str]:
    c = _get_unleash_api_client(api_url, client_access_token)

    return {k: "enabled" if v.enabled else "disabled" for k, v in c.features.items()}


def get_feature_toggle_strategies(toggle_name: str) -> Optional[list[Strategy]]:
    api_url = os.environ.get("UNLEASH_API_URL")
    client_access_token = os.environ.get("UNLEASH_CLIENT_ACCESS_TOKEN")
    if not (api_url and client_access_token):
        return None

    c = _get_unleash_api_client(api_url, client_access_token)
    all_strategies = {name: toggle.strategies for name, toggle in c.features.items()}

    return all_strategies[toggle_name] if toggle_name in all_strategies else None
