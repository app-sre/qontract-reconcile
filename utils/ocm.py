import json
import requests

import utils.secret_reader as secret_reader

from subprocess import Popen, PIPE

from utils.retry import retry


class StatusCodeError(Exception):
    pass


class NoOutputError(Exception):
    pass


class OCM(object):
    """OCM is an instance of OpenShift Cluster Manager"""
    def __init__(self, url, access_token_client_id, access_token_url,
                 offline_token):
        self.url = url
        self.access_token_client_id = access_token_client_id
        self.access_token_url = access_token_url
        self.offline_token = offline_token
        self._init_access_token()
        self._init_request_headers()
        self._init_clusters()

    def _init_access_token(self):
        data = {
            'grant_type': 'refresh_token',
            'client_id': self.access_token_client_id,
            'refresh_token': self.offline_token
        }
        r = requests.post(self.access_token_url, data=data)
        r.raise_for_status()
        self.access_token = r.json().get('access_token')

    def _init_request_headers(self):
        self.headers = {
            "Authorization": f"Bearer {self.access_token}",
            "accept": "application/json",
        }

    def _init_clusters(self):
        api = '/api/clusters_mgmt/v1/clusters'
        clusters = self._get_json(api)['items']
        self.cluster_ids = {c['name']: c['id'] for c in clusters}

    def get_group_if_exists(self, cluster, group_id):
        cluster_id = self.cluster_ids[cluster]
        api = f'/api/clusters_mgmt/v1/clusters/{cluster_id}/groups'
        groups = self._get_json(api)['items']
        if group_id not in [g['id'] for g in groups]:
            return None

        api = f'/api/clusters_mgmt/v1/clusters/{cluster_id}/groups/{group_id}/users'
        users = self._get_json(api)['items']
        return {'users': [u['id'] for u in users]}

    def add_user_to_group(self, group, user):
        return

    def del_user_from_group(self, group, user):
        return

    def _get_json(self, api):
        r = requests.get(f"{self.url}/{api}", headers=self.headers)
        r.raise_for_status()
        return r.json()

    @retry(exceptions=(StatusCodeError, NoOutputError))
    def _run(self, cmd, **kwargs):
        return


class OCMMap(object):
    """OCMMap gets a GraphQL query results list as input
    and initiates a dictionary of OCM clients per OCM.

    The input must contain either 'clusters' or 'namespaces', but not both.

    In case a cluster does not have an ocm instance
    the OCM client will be initiated to False.
    """
    def __init__(self, clusters=None, namespaces=None,
                 integration='', settings=None):
        self.clusters_map = {}
        self.ocm_map = {}
        self.calling_integration = integration
        self.settings = settings

        if clusters and namespaces:
            raise KeyError('expected only one of clusters or namespaces.')
        elif clusters:
            for cluster_info in clusters:
                self.init_ocm_client(cluster_info)
        elif namespaces:
            for namespace_info in namespaces:
                cluster_info = namespace_info['cluster']
                self.init_ocm_client(cluster_info)
        else:
            raise KeyError('expected one of clusters or namespaces.')

    def init_ocm_client(self, cluster_info):
        cluster_name = cluster_info['name']
        ocm_info = cluster_info['ocm']
        ocm_name = ocm_info['name']
        self.clusters_map[cluster_name] = ocm_name
        if self.ocm_map.get(ocm_name):
            return
        if self.cluster_disabled(cluster_info):
            return

        access_token_client_id = ocm_info.get('accessTokenClientId')
        access_token_url = ocm_info.get('accessTokenUrl')
        ocm_offline_token = ocm_info.get('offlineToken')
        if ocm_offline_token is None:
            self.ocm_map[ocm_name] = False
        else:
            url = ocm_info['url']
            token = secret_reader.read(ocm_offline_token, self.settings)
            self.ocm_map[ocm_name] = \
                OCM(url, access_token_client_id, access_token_url, token)

    def cluster_disabled(self, cluster_info):
        try:
            integrations = cluster_info['disable']['integrations']
            if self.calling_integration.replace('_', '-') in integrations:
                return True
        except (KeyError, TypeError):
            pass

        return False

    def get(self, cluster):
        ocm = self.clusters_map[cluster]
        return self.ocm_map.get(ocm, None)

    def clusters(self):
        return [k for k, v in self.clusters_map.items() if v]
