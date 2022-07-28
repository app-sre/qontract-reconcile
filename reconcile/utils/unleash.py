import os
import tempfile
import shutil
import threading

from UnleashClient import UnleashClient
from UnleashClient import strategies

from reconcile.utils.defer import defer
from reconcile.utils.helpers import toggle_logger

log_lock = threading.Lock()


def get_feature_toggle_default(feature_name, context):
    return True


@defer
def get_feature_toggle_state(integration_name, defer=None):
    api_url = os.environ.get("UNLEASH_API_URL")
    client_access_token = os.environ.get("UNLEASH_CLIENT_ACCESS_TOKEN")
    if not (api_url and client_access_token):
        return True

    # create temporary cache dir
    cache_dir = tempfile.mkdtemp()
    defer(lambda: shutil.rmtree(cache_dir))

    # hide INFO logging from UnleashClient
    with log_lock:
        with toggle_logger():
            # create Unleash client
            headers = {"Authorization": f"Bearer {client_access_token}"}
            client = UnleashClient(
                url=api_url,
                app_name="qontract-reconcile",
                custom_headers=headers,
                cache_directory=cache_dir,
            )
            client.initialize_client()

            # get feature toggle state
            state = client.is_enabled(
                integration_name, fallback_function=get_feature_toggle_default
            )
            client.destroy()

        return state


@defer
def get_feature_toggles(api_url, client_access_token, defer=None):
    # hide INFO logging from UnleashClient
    with toggle_logger():
        # create temporary cache dir
        cache_dir = tempfile.mkdtemp()
        defer(lambda: shutil.rmtree(cache_dir))

        # create Unleash client
        headers = {"Authorization": f"Bearer {client_access_token}"}
        client = UnleashClient(
            url=api_url,
            app_name="qontract-reconcile",
            custom_headers=headers,
            cache_directory=cache_dir,
        )
        client.initialize_client()
        defer(client.destroy)

    return {
        k: "enabled" if v.enabled else "disabled" for k, v in client.features.items()
    }


@defer
def get_unleash_strategies(api_url, token, strategy_names, defer=None):
    # create strategy mapping
    unleash_strategies = {name: strategies.Strategy for name in strategy_names}

    # create temporary cache dir
    cache_dir = tempfile.mkdtemp()
    defer(lambda: shutil.rmtree(cache_dir))

    # hide INFO logging from UnleashClient
    with log_lock:
        with toggle_logger():
            # create Unleash client
            headers = {"Authorization": f"Bearer {token}"}
            client = UnleashClient(
                url=api_url,
                app_name="qontract-reconcile",
                custom_headers=headers,
                cache_directory=cache_dir,
                custom_strategies=unleash_strategies,
            )
            client.initialize_client()

            strats = {
                name: toggle.strategies for name, toggle in client.features.items()
            }
            client.destroy()

        return strats


def get_feature_toggle_strategies(toggle_name, strategy_names):
    api_url = os.environ.get("UNLEASH_API_URL")
    client_access_token = os.environ.get("UNLEASH_CLIENT_ACCESS_TOKEN")
    if not (api_url and client_access_token):
        return None

    all_strategies = get_unleash_strategies(
        api_url=api_url, token=client_access_token, strategy_names=strategy_names
    )

    return all_strategies[toggle_name] if toggle_name in all_strategies else None
