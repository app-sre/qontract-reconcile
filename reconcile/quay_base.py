from reconcile.utils.secret_reader import SecretReader
import reconcile.queries as queries

from reconcile.utils.quay_api import QuayApi


def get_quay_api_store():
    """
    Returns a dictionary with a key for each Quay organization
    managed in app-interface.
    Each key contains an initiated QuayApi instance.
    """
    quay_orgs = queries.get_quay_orgs()
    settings = queries.get_app_interface_settings()
    secret_reader = SecretReader(settings=settings)
    store = {}
    for org_data in quay_orgs:
        name = org_data['name']
        server_url = org_data.get('serverUrl')
        token = secret_reader.read(org_data['automationToken'])
        store[name] = {
            'api': QuayApi(token, name, base_url=server_url),
            'teams': org_data.get('managedTeams')
        }

    return store
