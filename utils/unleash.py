import os
import logging
import tempfile
import shutil

from UnleashClient import UnleashClient

from utils.defer import defer


def get_feature_toggle_default(feature_name, context):
    return True


@defer
def get_feature_toggle_state(integration_name, defer=None):
    api_url = os.environ.get('UNLEASH_API_URL')
    client_access_token = os.environ.get('UNLEASH_CLIENT_ACCESS_TOKEN')
    if not (api_url and client_access_token):
        return True

    # hide INFO logging from UnleashClient
    logger = logging.getLogger()
    default_logging = logger.level
    logger.setLevel(logging.ERROR)
    defer(lambda: logger.setLevel(default_logging))

    # create temporary cache dir
    cache_dir = tempfile.mkdtemp()
    defer(lambda: shutil.rmtree(cache_dir))

    # create Unleash client
    headers = {'Authorization': f'Bearer {client_access_token}'}
    client = UnleashClient(url=api_url,
                           app_name='qontract-reconcile',
                           custom_headers=headers,
                           cache_directory=cache_dir)
    client.initialize_client()
    defer(lambda: client.destroy())

    # get feature toggle state
    state = client.is_enabled(integration_name,
                              fallback_function=get_feature_toggle_default)
    return state


@defer
def get_feature_toggles(api_url, client_access_token, defer=None):
    # hide INFO logging from UnleashClient
    logger = logging.getLogger()
    default_logging = logger.level
    logger.setLevel(logging.ERROR)
    defer(lambda: logger.setLevel(default_logging))

    # create temporary cache dir
    cache_dir = tempfile.mkdtemp()
    defer(lambda: shutil.rmtree(cache_dir))

    # create Unleash client
    headers = {'Authorization': f'Bearer {client_access_token}'}
    client = UnleashClient(url=api_url,
                           app_name='qontract-reconcile',
                           custom_headers=headers,
                           cache_directory=cache_dir)
    client.initialize_client()
    defer(lambda: client.destroy())

    return {k: 'enabled' if v.enabled else 'disabled'
            for k, v in client.features.items()}
