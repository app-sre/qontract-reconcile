from collections import namedtuple

from reconcile.utils.secret_reader import SecretReader
import reconcile.queries as queries

from reconcile.utils.quay_api import QuayApi

OrgKey = namedtuple('OrgKey', ['instance', 'org_name'])

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
        org_key = OrgKey(instance_name, org_name)
        base_url = org_data['instance']['url']
        token = secret_reader.read(org_data['automationToken'])
        store[org_key] = {
            'api': QuayApi(token, org_name, base_url=base_url),
            'teams': org_data.get('managedTeams')
        }

    return store
