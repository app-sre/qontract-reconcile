import json
import logging

import utils.secret_reader as secret_reader

from subprocess import Popen, PIPE

from utils.jump_host import JumpHostSSH
from utils.retry import retry


class StatusCodeError(Exception):
    pass


class NoOutputError(Exception):
    pass


class JSONParsingError(Exception):
    pass


class RecyclePodsUnsupportedKindError(Exception):
    pass


class PodNotReadyError(Exception):
    pass


class OC(object):
    def __init__(self, server, token, jh=None, settings=None):
        oc_base_cmd = [
            'oc',
            '--config', '/dev/null',
            '--server', server,
            '--token', token
        ]

        if jh is not None:
            self.jump_host = JumpHostSSH(jh, settings=settings)
            oc_base_cmd = self.jump_host.get_ssh_base_cmd() + oc_base_cmd

        self.oc_base_cmd = oc_base_cmd

    def whoami(self):
        return self._run(['whoami'])

    def cleanup(self):
        if hasattr(self, 'jump_host') and \
                isinstance(self.jump_host, JumpHostSSH):
            self.jump_host.cleanup()

    def get_items(self, kind, **kwargs):
        cmd = ['get', kind, '-o', 'json']

        if 'namespace' in kwargs:
            namespace = kwargs['namespace']
            # for cluster scoped integrations
            # currently only openshift-clusterrolebindings
            if namespace != 'cluster':
                if not self.project_exists(namespace):
                    return []
                cmd.extend(['-n', namespace])

        if 'labels' in kwargs:
            labels_list = [
                "{}={}".format(k, v)
                for k, v in kwargs.get('labels').items()
            ]

            cmd.append('-l')
            cmd.append(','.join(labels_list))

        items_list = self._run_json(cmd)

        items = items_list.get('items')
        if items is None:
            raise Exception("Expecting items")

        return items

    def get(self, namespace, kind, name=None):
        cmd = ['get', '-o', 'json', kind]
        if name:
            cmd.append(name)
        if namespace is not None:
            cmd.extend(['-n', namespace])
        return self._run_json(cmd)

    def get_all(self, kind, all_namespaces=False):
        cmd = ['get', '-o', 'json', kind]
        if all_namespaces:
            cmd.append('--all-namespaces')
        return self._run_json(cmd)

    def apply(self, namespace, resource):
        cmd = ['apply', '-n', namespace, '-f', '-']
        self._run(cmd, stdin=resource)

    def delete(self, namespace, kind, name):
        cmd = ['delete', '-n', namespace, kind, name]
        self._run(cmd)

    def project_exists(self, name):
        try:
            self.get(None, 'Project', name)
        except StatusCodeError as e:
            if 'NotFound' in str(e):
                return False
            else:
                raise e
        return True

    def new_project(self, namespace):
        cmd = ['new-project', namespace]
        self._run(cmd)

    def delete_project(self, namespace):
        cmd = ['delete', 'project', namespace]
        self._run(cmd)

    def get_group_if_exists(self, name):
        try:
            return self.get(None, 'Group', name)
        except StatusCodeError as e:
            if 'NotFound' in str(e):
                return None
            else:
                raise e

    def create_group(self, group):
        cmd = ['adm', 'groups', 'new', group]
        self._run(cmd)

    def delete_group(self, group):
        cmd = ['delete', 'group', group]
        self._run(cmd)

    def get_users(self):
        return self.get_all('Users')['items']

    def delete_user(self, user_name):
        user = self.get(None, 'User', user_name)
        cmd = ['delete', 'user', user_name]
        self._run(cmd)
        for identity in user['identities']:
            cmd = ['delete', 'identity', identity]
            self._run(cmd)

    def add_user_to_group(self, group, user):
        cmd = ['adm', 'groups', 'add-users', group, user]
        self._run(cmd)

    def del_user_from_group(self, group, user):
        cmd = ['adm', 'groups', 'remove-users', group, user]
        self._run(cmd)

    @staticmethod
    def get_service_account_username(user):
        namespace = user.split('/')[0]
        name = user.split('/')[1]
        return "system:serviceaccount:{}:{}".format(namespace, name)

    def recycle_pods(self, namespace, dep_kind, dep_name):
        """ recycles pods which are using the specified resources.
        dep_kind: dependant resource type. currently only supports Secret.
        dep_name: name of the dependant resource. """

        pods = self.get(namespace, 'Pods')['items']

        if dep_kind == 'Secret':
            pods_to_recycle = [pod['metadata']['name'] for pod in pods
                               if self.secret_used_in_pod(dep_name, pod)]
        else:
            raise RecyclePodsUnsupportedKindError(dep_kind)

        for pod in pods_to_recycle:
            logging.info(['recycle_pod', namespace, pod])
            self.delete(namespace, 'Pod', pod)
            logging.info(['validating_pods', namespace])
            self.validate_pods_ready(
                namespace, self.secret_used_in_pod, dep_name)

    @staticmethod
    def secret_used_in_pod(secret_name, pod):
        volumes = pod['spec']['volumes']
        for v in volumes:
            secret = v.get('secret', {})
            try:
                if secret['secretName'] == secret_name:
                    return True
            except KeyError:
                continue
        containers = pod['spec']['containers']
        for c in containers:
            for e in c.get('envFrom', []):
                try:
                    if e['secretRef']['name'] == secret_name:
                        return True
                except KeyError:
                    continue
            for e in c.get('env', []):
                try:
                    if e['valueFrom']['secretKeyRef']['name'] == secret_name:
                        return True
                except KeyError:
                    continue
        return False

    @retry(exceptions=PodNotReadyError, max_attempts=20)
    def validate_pods_ready(self, namespace, filter_method, dep_name):
        pods = self.get(namespace, 'Pods')['items']
        pods_to_validate = [pod for pod in pods
                            if filter_method(dep_name, pod)]
        for pod in pods_to_validate:
            for status in pod['status']['containerStatuses']:
                if not status['ready']:
                    raise PodNotReadyError(pod['metadata']['name'])

    @retry(exceptions=(StatusCodeError, NoOutputError))
    def _run(self, cmd, **kwargs):
        if kwargs.get('stdin'):
            stdin = PIPE
            stdin_text = kwargs.get('stdin').encode()
        else:
            stdin = None
            stdin_text = None

        p = Popen(
            self.oc_base_cmd + cmd,
            stdin=stdin,
            stdout=PIPE,
            stderr=PIPE
        )
        out, err = p.communicate(stdin_text)

        code = p.returncode

        if code != 0:
            raise StatusCodeError(err)

        if not out:
            raise NoOutputError(err)

        return out.strip()

    def _run_json(self, cmd):
        out = self._run(cmd)

        try:
            out_json = json.loads(out)
        except ValueError as e:
            raise JSONParsingError(out + "\n" + str(e))

        return out_json


class OC_Map(object):
    """OC_Map gets a GraphQL query results list as input
    and initiates a dictionary of OC clients per cluster.

    The input must contain either 'clusters' or 'namespaces', but not both.

    In case a cluster does not have an automation token
    the OC client will be initiated to False.
    """
    def __init__(self, clusters=None, namespaces=None,
                 integration='', e2e_test='', settings=None,
                 internal=None):
        self.oc_map = {}
        self.calling_integration = integration
        self.calling_e2e_test = e2e_test
        self.settings = settings
        self.internal = internal

        if clusters and namespaces:
            raise KeyError('expected only one of clusters or namespaces.')
        elif clusters:
            for cluster_info in clusters:
                self.init_oc_client(cluster_info)
        elif namespaces:
            for namespace_info in namespaces:
                cluster_info = namespace_info['cluster']
                self.init_oc_client(cluster_info)
        else:
            raise KeyError('expected one of clusters or namespaces.')

    def init_oc_client(self, cluster_info):
        cluster = cluster_info['name']
        if self.oc_map.get(cluster):
            return
        if self.cluster_disabled(cluster_info):
            return
        if self.internal is not None:
            # integration is executed with `--internal` or `--external`
            # filter out non matching clusters
            if self.internal and not cluster_info['internal']:
                return
            if not self.internal and cluster_info['internal']:
                return

        automation_token = cluster_info.get('automationToken')
        if automation_token is None:
            self.oc_map[cluster] = False
        else:
            server_url = cluster_info['serverUrl']
            token = secret_reader.read(automation_token, self.settings)
            jump_host = cluster_info.get('jumpHost')
            self.oc_map[cluster] = OC(server_url, token, jump_host,
                                      settings=self.settings)

    def cluster_disabled(self, cluster_info):
        try:
            integrations = cluster_info['disable']['integrations']
            if self.calling_integration.replace('_', '-') in integrations:
                return True
        except (KeyError, TypeError):
            pass
        try:
            tests = cluster_info['disable']['e2eTests']
            if self.calling_e2e_test.replace('_', '-') in tests:
                return True
        except (KeyError, TypeError):
            pass

        return False

    def get(self, cluster):
        return self.oc_map.get(cluster, None)

    def clusters(self):
        return [k for k, v in self.oc_map.items() if v]

    def cleanup(self):
        for oc in self.oc_map.values():
            if oc:
                oc.cleanup()
