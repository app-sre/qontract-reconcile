import requests
import logging

from sretoolbox.utils import retry

from utils.secret_reader import SecretReader


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
        self._init_addons()

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
                         for c in clusters if c['managed']
                         and c['state'] == 'ready'}
        self.not_ready_clusters = [c['name'] for c in clusters
                                   if c['managed'] and c['state'] != 'ready']

    def _get_cluster_ocm_spec(self, cluster):
        ocm_spec = {
            'spec': {
                'id': cluster['id'],
                'external_id': cluster['external_id'],
                'provider': cluster['cloud_provider']['id'],
                'region': cluster['region']['id'],
                'channel': cluster['version']['channel_group'],
                'version': cluster['openshift_version'],
                'multi_az': cluster['multi_az'],
                'nodes': cluster['nodes']['compute'],
                'instance_type':
                    cluster['nodes']['compute_machine_type']['id'],
                'storage':
                    int(cluster['storage_quota']['value'] / pow(1024, 3)),
                'load_balancers': cluster['load_balancer_quota'],
                'private': cluster['api']['listening'] == 'internal',
                'provision_shard_id':
                    self.get_provision_shard(cluster['id'])['id']
            },
            'network': {
                'vpc': cluster['network']['machine_cidr'],
                'service': cluster['network']['service_cidr'],
                'pod': cluster['network']['pod_cidr']
            }
        }
        return ocm_spec

    def create_cluster(self, name, cluster, dry_run):
        """
        Creates a cluster.

        :param name: name of the cluster
        :param cluster: a dictionary representing a cluster desired state
        :param dry_run: do not execute for real

        :type name: string
        :type cluster: dict
        :type dry_run: bool
        """
        api = f'/api/clusters_mgmt/v1/clusters'
        cluster_spec = cluster['spec']
        cluster_network = cluster['network']
        ocm_spec = {
            'name': name,
            'cloud_provider': {
                'id': cluster_spec['provider']
            },
            'region': {
                'id': cluster_spec['region']
            },
            'version': {
                'id': 'openshift-v' + cluster_spec['initial_version'],
                'channel_group': cluster_spec['channel']
            },
            'multi_az': cluster_spec['multi_az'],
            'nodes': {
                'compute': cluster_spec['nodes'],
                'compute_machine_type': {
                    'id': cluster_spec['instance_type']
                }
            },
            'storage_quota': {
                'value': float(cluster_spec['storage'] * pow(1024, 3))
            },
            'load_balancer_quota': cluster_spec['load_balancers'],
            'network': {
                'machine_cidr': cluster_network['vpc'],
                'service_cidr': cluster_network['service'],
                'pod_cidr': cluster_network['pod'],
            },
            'api': {
                'listening':
                    'internal' if cluster_spec['private']
                    else 'external'
            }
        }

        provision_shard_id = cluster_spec.get('provision_shard_id')
        if provision_shard_id:
            ocm_spec.setdefault('properties', {})
            ocm_spec['properties']['provision_shard_id'] = provision_shard_id

        params = {}
        if dry_run:
            params['dryRun'] = 'true'

        self._post(api, ocm_spec, params)

    def get_group_if_exists(self, cluster, group_id):
        """Returns a list of users in a group in a cluster.
        If the group does not exist, None will be returned.

        :param cluster: cluster name
        :param group_id: group name

        :type cluster: string
        :type group_id: string
        """
        cluster_id = self.cluster_ids.get(cluster)
        if not cluster_id:
            return None
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

    def get_aws_infrastructure_access_role_grants(self, cluster):
        """Returns a list of AWS users (ARN, access level)
        who have AWS infrastructure access in a cluster.

        :param cluster: cluster name

        :type cluster: string
        """
        cluster_id = self.cluster_ids.get(cluster)
        if not cluster_id:
            return []
        api = f'/api/clusters_mgmt/v1/clusters/{cluster_id}/' + \
              f'aws_infrastructure_access_role_grants'
        role_grants = self._get_json(api)['items']
        return [(r['user_arn'], r['role']['id']) for r in role_grants]

    def get_aws_infrastructure_access_terraform_assume_role(self, cluster,
                                                            tf_account_id,
                                                            tf_user):
        cluster_id = self.cluster_ids[cluster]
        api = f'/api/clusters_mgmt/v1/clusters/{cluster_id}/' + \
              f'aws_infrastructure_access_role_grants'
        role_grants = self._get_json(api)['items']
        user_arn = f"arn:aws:iam::{tf_account_id}:user/{tf_user}"
        for rg in role_grants:
            if rg['user_arn'] != user_arn:
                continue
            if rg['role']['id'] != 'network-mgmt':
                continue
            console_url = rg['console_url']
            # split out only the url arguments
            account_and_role = console_url.split('?')[1]
            account, role = account_and_role.split('&')
            role_account_id = account.replace('account=', '')
            role_name = role.replace('roleName=', '')
            return f"arn:aws:iam::{role_account_id}:role/{role_name}"

    def add_user_to_aws_infrastructure_access_role_grants(self, cluster,
                                                          user_arn,
                                                          access_level):
        """
        Adds a user to AWS infrastructure access in a cluster.

        :param cluster: cluster name
        :param user_arn: user ARN
        :param access_level: access level (read-only or network-mgmt)

        :type cluster: string
        :type user_arn: string
        :type access_level: string
        """
        cluster_id = self.cluster_ids[cluster]
        api = f'/api/clusters_mgmt/v1/clusters/{cluster_id}/' + \
              f'aws_infrastructure_access_role_grants'
        self._post(api, {'user_arn': user_arn, 'role': {'id': access_level}})

    def del_user_from_aws_infrastructure_access_role_grants(self, cluster,
                                                            user_arn,
                                                            access_level):
        """
        Deletes a user from AWS infrastructure access in a cluster.

        :param cluster: cluster name
        :param user_arn: user ARN
        :param access_level: access level (read-only or network-mgmt)

        :type cluster: string
        :type user_arn: string
        :type access_level: string
        """
        cluster_id = self.cluster_ids[cluster]
        api = f'/api/clusters_mgmt/v1/clusters/{cluster_id}/' + \
              f'aws_infrastructure_access_role_grants'
        role_grants = self._get_json(api)['items']
        for rg in role_grants:
            if rg['user_arn'] != user_arn:
                continue
            if rg['role']['id'] != access_level:
                continue
            aws_infrastructure_access_role_grant_id = rg['id']
            self._delete(f"{api}/{aws_infrastructure_access_role_grant_id}")

    def get_github_idp_teams(self, cluster):
        """Returns a list of details of GitHub IDP providers

        :param cluster: cluster name

        :type cluster: string
        """
        result_idps = []
        cluster_id = self.cluster_ids.get(cluster)
        if not cluster_id:
            return result_idps
        api = \
            f'/api/clusters_mgmt/v1/clusters/{cluster_id}/identity_providers'
        idps = self._get_json(api).get('items')
        if not idps:
            return result_idps

        for idp in idps:
            if idp['type'] != 'GithubIdentityProvider':
                continue
            if idp['mapping_method'] != 'claim':
                continue
            idp_name = idp['name']
            idp_github = idp['github']

            item = {
                'cluster': cluster,
                'name': idp_name,
                'client_id': idp_github['client_id'],
                'teams': idp_github.get('teams')
            }
            result_idps.append(item)
        return result_idps

    def create_github_idp_teams(self, spec):
        """Creates a new GitHub IDP

        :param cluster: cluster name
        :param spec: required information for idp creation

        :type cluster: string
        :type spec: dictionary
        """
        cluster = spec['cluster']
        cluster_id = self.cluster_ids[cluster]
        api = \
            f'/api/clusters_mgmt/v1/clusters/{cluster_id}/identity_providers'
        payload = {
            'type': 'GithubIdentityProvider',
            'mapping_method': 'claim',
            'name': spec['name'],
            'github': {
                'client_id': spec['client_id'],
                'client_secret': spec['client_secret'],
                'teams': spec['teams']
            }
        }
        self._post(api, payload)

    def get_external_configuration_labels(self, cluster):
        """Returns details of External Configurations

        :param cluster: cluster name

        :type cluster: string
        """
        results = {}
        cluster_id = self.cluster_ids.get(cluster)
        if not cluster_id:
            return results
        api = \
            f'/api/clusters_mgmt/v1/clusters/{cluster_id}' + \
            f'/external_configuration/labels'
        items = self._get_json(api).get('items')
        if not items:
            return results

        for item in items:
            key = item['key']
            value = item['value']
            results[key] = value

        return results

    def create_external_configuration_label(self, cluster, label):
        """Creates a new External Configuration label

        :param cluster: cluster name
        :param label: key and value for new label

        :type cluster: string
        :type label: dictionary
        """
        cluster_id = self.cluster_ids[cluster]
        api = \
            f'/api/clusters_mgmt/v1/clusters/{cluster_id}' + \
            f'/external_configuration/labels'
        self._post(api, label)

    def delete_external_configuration_labels(self, cluster, label):
        """Deletes an existing External Configuration label

        :param cluster: cluster name
        :param label:  key and value of label to delete

        :type cluster: string
        :type label: dictionary
        """
        cluster_id = self.cluster_ids[cluster]
        api = \
            f'/api/clusters_mgmt/v1/clusters/{cluster_id}' + \
            f'/external_configuration/labels'
        items = self._get_json(api).get('items')
        item = [item for item in items if label.items() <= item.items()]
        if not item:
            return
        label_id = item[0]['id']
        api = \
            f'/api/clusters_mgmt/v1/clusters/{cluster_id}' + \
            f'/external_configuration/labels/{label_id}'
        self._delete(api)

    def get_machine_pools(self, cluster):
        """Returns a list of details of Machine Pools

        :param cluster: cluster name

        :type cluster: string
        """
        results = []
        cluster_id = self.cluster_ids.get(cluster)
        if not cluster_id:
            return results
        api = \
            f'/api/clusters_mgmt/v1/clusters/{cluster_id}/machine_pools'
        items = self._get_json(api).get('items')
        if not items:
            return results

        for item in items:
            desired_keys = ['id', 'instance_type', 'replicas', 'labels']
            result = {k: v for k, v in item.items() if k in desired_keys}
            results.append(result)

        return results

    def create_machine_pool(self, cluster, spec):
        """Creates a new Machine Pool

        :param cluster: cluster name
        :param spec: required information for machine pool creation

        :type cluster: string
        :type spec: dictionary
        """
        cluster_id = self.cluster_ids[cluster]
        api = \
            f'/api/clusters_mgmt/v1/clusters/{cluster_id}/machine_pools'
        self._post(api, spec)

    def update_machine_pool(self, cluster, spec):
        """Updates an existing Machine Pool

        :param cluster: cluster name
        :param spec: required information for machine pool update

        :type cluster: string
        :type spec: dictionary
        """
        cluster_id = self.cluster_ids[cluster]
        machine_pool_id = spec['id']
        api = \
            f'/api/clusters_mgmt/v1/clusters/{cluster_id}/machine_pools/' + \
            f'{machine_pool_id}'
        self._patch(api, spec)

    def delete_machine_pool(self, cluster, spec):
        """Deletes an existing Machine Pool

        :param cluster: cluster name
        :param spec: required information for machine pool update

        :type cluster: string
        :type spec: dictionary
        """
        cluster_id = self.cluster_ids[cluster]
        machine_pool_id = spec['id']
        api = \
            f'/api/clusters_mgmt/v1/clusters/{cluster_id}/machine_pools/' + \
            f'{machine_pool_id}'
        self._delete(api)

    def get_upgrade_policies(self, cluster, schedule_type=None):
        """Returns a list of details of Upgrade Policies

        :param cluster: cluster name

        :type cluster: string
        """
        results = []
        cluster_id = self.cluster_ids.get(cluster)
        if not cluster_id:
            return results
        api = \
            f'/api/clusters_mgmt/v1/clusters/{cluster_id}/upgrade_policies'
        items = self._get_json(api).get('items')
        if not items:
            return results

        for item in items:
            if schedule_type and item['schedule_type'] != schedule_type:
                continue
            desired_keys = ['id', 'schedule_type', 'schedule', 'next_run']
            result = {k: v for k, v in item.items() if k in desired_keys}
            results.append(result)

        return results

    def create_upgrade_policy(self, cluster, spec):
        """Creates a new Upgrade Policy

        :param cluster: cluster name
        :param spec: required information for creation

        :type cluster: string
        :type spec: dictionary
        """
        cluster_id = self.cluster_ids[cluster]
        api = \
            f'/api/clusters_mgmt/v1/clusters/{cluster_id}/upgrade_policies'
        self._post(api, spec)

    def delete_upgrade_policy(self, cluster, spec):
        """Deletes an existing Upgrade Policy

        :param cluster: cluster name
        :param spec: required information for update

        :type cluster: string
        :type spec: dictionary
        """
        cluster_id = self.cluster_ids[cluster]
        upgrade_policy_id = spec['id']
        api = \
            f'/api/clusters_mgmt/v1/clusters/{cluster_id}/' + \
            f'upgrade_policies/{upgrade_policy_id}'
        self._delete(api)

    def get_provision_shard(self, cluster_id):
        """Returns details of the provision shard

        :param cluster: cluster id

        :type cluster: string
        """
        api = \
            f'/api/clusters_mgmt/v1/clusters/{cluster_id}/provision_shard'
        return self._get_json(api)

    def get_pull_secrets(self,):
        api = '/api/accounts_mgmt/v1/access_token'
        return self._post(api)

    def get_kafka_clusters(self, fields=None):
        """Returns details of the Kafka clusters """
        api = '/api/managed-services-api/v1/kafkas'
        clusters = self._get_json(api)['items']
        if fields:
            clusters = [{k: v for k, v in cluster.items()
                         if k in fields}
                        for cluster in clusters]
        return clusters

    def create_kafka_cluster(self, data):
        """Creates (async) a Kafka cluster """
        api = '/api/managed-services-api/v1/kafkas'
        params = {'async': 'true'}
        self._post(api, data, params)

    def _init_addons(self):
        """Returns a list of Addons """
        api = '/api/clusters_mgmt/v1/addons'
        self.addons = self._get_json(api).get('items')

    def get_addon(self, name):
        for addon in self.addons:
            resource_name = addon['resource_name']
            if name == resource_name:
                return addon
        return None

    def get_cluster_addons(self, cluster):
        """Returns a list of Addons installed on a cluster

        :param cluster: cluster name

        :type cluster: string
        """
        results = []
        cluster_id = self.cluster_ids.get(cluster)
        if not cluster_id:
            return results
        api = \
            f'/api/clusters_mgmt/v1/clusters/{cluster_id}/addons'
        items = self._get_json(api).get('items')
        if not items:
            return results

        for item in items:
            desired_keys = ['id']
            result = {k: v for k, v in item.items() if k in desired_keys}
            results.append(result)

        return results

    def install_addon(self, cluster, spec):
        """ Installs an addon on a cluster

        :param cluster: cluster name
        :param spec: required information for installation

        :type cluster: string
        :type spec: dictionary ({'id': <addon_id>})
        """
        cluster_id = self.cluster_ids[cluster]
        api = \
            f'/api/clusters_mgmt/v1/clusters/{cluster_id}/addons'
        data = {'addon': spec}
        self._post(api, data)

    @retry(max_attempts=10)
    def _get_json(self, api):
        r = requests.get(f"{self.url}{api}", headers=self.headers)
        r.raise_for_status()
        return r.json()

    def _post(self, api, data=None, params=None):
        r = requests.post(
            f"{self.url}{api}",
            headers=self.headers,
            json=data,
            params=params
        )
        try:
            r.raise_for_status()
        except Exception as e:
            logging.error(r.text)
            raise e
        if r.status_code == requests.codes.no_content:
            return None
        return r.json()

    def _patch(self, api, data):
        r = requests.patch(
            f"{self.url}{api}", headers=self.headers, json=data)
        try:
            r.raise_for_status()
        except Exception as e:
            logging.error(r.text)
            raise e

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
            secret_reader = SecretReader(settings=self.settings)
            token = secret_reader.read(ocm_offline_token)
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

        not_ready_cluster_names = []
        for v in self.ocm_map.values():
            not_ready_cluster_names.extend(v.not_ready_clusters)
        return cluster_specs, not_ready_cluster_names

    def kafka_cluster_specs(self):
        """Get dictionary of Kafka cluster names and specs in the OCM map."""
        fields = ['id', 'status', 'cloud_provider', 'region',
                  'name', 'bootstrapServerHost']
        cluster_specs = []
        for ocm in self.ocm_map.values():
            clusters = ocm.get_kafka_clusters(fields=fields)
            cluster_specs.extend(clusters)
        return cluster_specs
