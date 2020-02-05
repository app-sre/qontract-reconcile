import requests

import utils.secret_reader as secret_reader
from utils.retry import retry


class OCM(object):
    """
    OCM is an instance of OpenShift Cluster Manager.

    :param url: OCM instance URL
    :param access_token_client_id: client-id to get access token
    :param access_token_url: URL to get access token from
    :param offline_token: Long lived offline token used to get access token
    :type url: string
    :type access_token_client_id: string
    :type access_token_url: string
    :type offline_token: string
    """
    def __init__(self, url, access_token_client_id, access_token_url,
                 offline_token):
        """Initiates access token and gets clusters information."""
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
        self.clusters = {c['name']: self._get_cluster_ocm_spec(c)
                         for c in clusters if c['managed']}

    @staticmethod
    def _get_cluster_ocm_spec(cluster):
        ocm_spec = {
            'spec': {
                'provider': cluster['cloud_provider']['id'],
                'region': cluster['region']['id'],
                'major_version':
                    int(cluster['openshift_version'].split('.')[0]),
                'multi_az': cluster['multi_az'],
                'nodes': cluster['nodes']['compute'],
                'instance_type':
                    cluster['nodes']['compute_machine_type']['id'],
                'storage': int(cluster['storage_quota']['value'] / pow(1024, 3)),
                'load_balancers': cluster['load_balancer_quota']
            },
            'network': {
                'vpc': cluster['network']['machine_cidr'],
                'service': cluster['network']['service_cidr'],
                'pod': cluster['network']['pod_cidr']
            }
        }
        return ocm_spec

    def get_group_if_exists(self, cluster, group_id):
        """Returns a list of users in a group in a cluster.
        If the group does not exist, None will be returned.

        :param cluster: cluster name
        :param group_id: group name

        :type cluster: string
        :type group_id: string
        """
        cluster_id = self.cluster_ids[cluster]
        api = f'/api/clusters_mgmt/v1/clusters/{cluster_id}/groups'
        groups = self._get_json(api)['items']
        if group_id not in [g['id'] for g in groups]:
            return None

        api = f'/api/clusters_mgmt/v1/clusters/{cluster_id}/' + \
              f'groups/{group_id}/users'
        users = self._get_json(api)['items']
        return {'users': [u['id'] for u in users]}

    def add_user_to_group(self, cluster, group_id, user):
        """
        Adds a user to a group in a cluster.

        :param cluster: cluster name
        :param group_id: group name
        :param user: user name

        :type cluster: string
        :type group_id: string
        :type user: string
        """
        cluster_id = self.cluster_ids[cluster]
        api = f'/api/clusters_mgmt/v1/clusters/{cluster_id}/' + \
              f'groups/{group_id}/users'
        self._post(api, {'id': user})

    def del_user_from_group(self, cluster, group_id, user_id):
        """Deletes a user from a group in a cluster.

        :param cluster: cluster name
        :param group_id: group name
        :param user: user name

        :type cluster: string
        :type group_id: string
        :type user: string
        """
        cluster_id = self.cluster_ids[cluster]
        api = f'/api/clusters_mgmt/v1/clusters/{cluster_id}/' + \
              f'groups/{group_id}/users/{user_id}'
        self._delete(api)

    @retry(max_attempts=10)
    def _get_json(self, api):
        r = requests.get(f"{self.url}{api}", headers=self.headers)
        r.raise_for_status()
        return r.json()

    def _post(self, api, data):
        r = requests.post(f"{self.url}{api}", headers=self.headers, json=data)
        r.raise_for_status()

    def _delete(self, api):
        r = requests.delete(f"{self.url}{api}", headers=self.headers)
        r.raise_for_status()


class OCMMap(object):
    """
    OCMMap gets a GraphQL query results list as input
    and initiates a dictionary of OCM clients per OCM.

    The input must contain either 'clusters' or 'namespaces', but not both.

    In case a cluster does not have an ocm instance
    the OCM client will be initiated to False.

    :param clusters: Graphql clusters query results list
    :param namespaces: Graphql namespaces query results list
    :param integration: Name of calling integration.
                        Used to disable integrations.
    :param settings: App Interface settings
    :type clusters: list
    :type namespaces: list
    :type integration: string
    :type settings: dict
    """
    def __init__(self, clusters=None, namespaces=None,
                 integration='', settings=None):
        """Initiates OCM instances for each OCM referenced in a cluster."""
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
        """
        Initiate OCM client.
        Gets the OCM information and initiates an OCM client.
        Skip initiating OCM if it has already been initialized or if
        the current integration is disabled on it.

        :param cluster_info: Graphql cluster query result

        :type cluster_info: dict
        """
        if self.cluster_disabled(cluster_info):
            return
        cluster_name = cluster_info['name']
        ocm_info = cluster_info['ocm']
        ocm_name = ocm_info['name']
        # pointer from each cluster to its referenced OCM instance
        self.clusters_map[cluster_name] = ocm_name
        if self.ocm_map.get(ocm_name):
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
        """
        Checks if the calling integration is disabled in this cluster.

        :param cluster_info: Graphql cluster query result

        :type cluster_info: dict
        """
        try:
            integrations = cluster_info['disable']['integrations']
            if self.calling_integration.replace('_', '-') in integrations:
                return True
        except (KeyError, TypeError):
            pass

        return False

    def get(self, cluster):
        """
        Gets an OCM instance by cluster.

        :param cluster: cluster name

        :type cluster: string
        """
        ocm = self.clusters_map[cluster]
        return self.ocm_map.get(ocm, None)

    def clusters(self):
        """Get list of cluster names initiated in the OCM map."""
        return [k for k, v in self.clusters_map.items() if v]

    def cluster_specs(self):
        """Get dictionary of cluster names and specs in the OCM map."""
        cluster_specs = {}
        for v in self.ocm_map.values():
            cluster_specs.update(v.clusters)
        return cluster_specs
