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
        instance_name = org_data['instance']['name']
        org_name = org_data['name']
        key = (instance_name, org_name)
        api_url = org_data['instance']['url']
        token = secret_reader.read(org_data['automationToken'])
        store[key] = {
            'api': QuayApi(token, org_name, api_url=api_url),
            'teams': org_data.get('managedTeams')
        }

    return store
