import json
import logging

from subprocess import Popen, PIPE
from datetime import datetime

from sretoolbox.utils import retry

from utils import secret_reader
from utils.jump_host import JumpHostSSH


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
        self.server = server
        oc_base_cmd = [
            'oc',
            '--kubeconfig', '/dev/null',
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

        resource_names = kwargs.get('resource_names')
        if resource_names:
            items = []
            for resource_name in resource_names:
                resource_cmd = cmd + [resource_name]
                item = self._run_json(resource_cmd, allow_not_found=True)
                if item:
                    items.append(item)
            items_list = {'items': items}
        else:
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

    def process(self, template, parameters={}):
        parameters_to_process = [f"{k}={v}" for k, v in parameters.items()]
        cmd = [
            'process',
            '--local',
            '--ignore-unknown-parameters',
            '-f', '-'
        ] + parameters_to_process
        result = self._run(cmd, stdin=json.dumps(template, sort_keys=True))
        return json.loads(result)['items']

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

    def sa_get_token(self, namespace, name):
        cmd = ['sa', '-n', namespace, 'get-token', name]
        return self._run(cmd)

    @staticmethod
    def get_service_account_username(user):
        namespace = user.split('/')[0]
        name = user.split('/')[1]
        return "system:serviceaccount:{}:{}".format(namespace, name)

    def recycle_pods(self, dry_run, namespace, dep_kind, dep_resource):
        """ recycles pods which are using the specified resources.
        will only act on Secrets containing the 'qontract.recycle' annotation.
        dry_run: simulate pods recycle.
        namespace: namespace in which dependant resource is applied.
        dep_kind: dependant resource kind. currently only supports Secret.
        dep_resource: dependant resource. """

        supported_kinds = ['Secret', 'ConfigMap']
        if dep_kind not in supported_kinds:
            logging.debug(['skipping_pod_recycle_unsupported',
                           namespace, dep_kind])
            return

        dep_annotations = dep_resource.body['metadata'].get('annotations', {})
        if dep_annotations.get('qontract.recycle') != 'true':
            logging.debug(['skipping_pod_recycle_no_annotation',
                           namespace, dep_kind])
            return

        dep_name = dep_resource.name
        pods = self.get(namespace, 'Pods')['items']

        if dep_kind == 'Secret':
            pods_to_recycle = [pod for pod in pods
                               if self.secret_used_in_pod(dep_name, pod)]
        elif dep_kind == 'ConfigMap':
            pods_to_recycle = [pod for pod in pods
                               if self.configmap_used_in_pod(dep_name, pod)]
        else:
            raise RecyclePodsUnsupportedKindError(dep_kind)

        recyclables = {}
        supported_recyclables = ['Deployment', 'DeploymentConfig']
        for pod in pods_to_recycle:
            owner = self.get_obj_root_owner(namespace, pod)
            kind = owner['kind']
            if kind not in supported_recyclables:
                continue
            recyclables.setdefault(kind, [])
            exists = False
            for obj in recyclables[kind]:
                owner_name = owner['metadata']['name']
                if obj['metadata']['name'] == owner_name:
                    exists = True
                    break
            if not exists:
                recyclables[kind].append(owner)

        for kind, objs in recyclables.items():
            for obj in objs:
                name = obj['metadata']['name']
                logging.info([f'recycle_{kind.lower()}', namespace, name])
                if not dry_run:
                    now = datetime.now()
                    recycle_time = now.strftime("%d/%m/%Y %H:%M:%S")

                    # honor update strategy by setting annotations to force
                    # a new rollout
                    a = obj['spec']['template']['metadata'].get(
                        'annotations', {})
                    a['recycle.time'] = recycle_time
                    obj['spec']['template']['metadata']['annotations'] = a
                    self.apply(namespace, json.dumps(obj, sort_keys=True))

    def get_obj_root_owner(self, ns, obj):
        refs = obj['metadata'].get('ownerReferences', [])
        for r in refs:
            if r.get('controller'):
                controller_obj = self.get(ns, r['kind'], r['name'])
                return self.get_obj_root_owner(ns, controller_obj)
        return obj

    @staticmethod
    def secret_used_in_pod(name, pod):
        volumes = pod['spec']['volumes']
        for v in volumes:
            volume_item = v.get('secret', {})
            try:
                if volume_item['secretName'] == name:
                    return True
            except KeyError:
                continue
        containers = pod['spec']['containers']
        for c in containers:
            for e in c.get('envFrom', []):
                try:
                    if e['secretRef']['name'] == name:
                        return True
                except KeyError:
                    continue
            for e in c.get('env', []):
                try:
                    if e['valueFrom']['secretKeyRef']['name'] == name:
                        return True
                except KeyError:
                    continue
        return False

    @staticmethod
    def configmap_used_in_pod(name, pod):
        volumes = pod['spec']['volumes']
        for v in volumes:
            volume_item = v.get('configMap', {})
            try:
                if volume_item['name'] == name:
                    return True
            except KeyError:
                continue
        containers = pod['spec']['containers']
        for c in containers:
            for e in c.get('envFrom', []):
                try:
                    if e['configMapRef']['name'] == name:
                        return True
                except KeyError:
                    continue
            for e in c.get('env', []):
                try:
                    if e['valueFrom']['configMapKeyRef']['name'] == name:
                        return True
                except KeyError:
                    continue
        return False

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

        allow_not_found = kwargs.get('allow_not_found')

        if code != 0:
            err = err.decode('utf-8')
            if not (allow_not_found and 'NotFound' in err):
                raise StatusCodeError(f"[{self.server}]: {err}")

        if not out:
            if allow_not_found:
                return '{}'
            else:
                raise NoOutputError(err)

        return out.strip()

    def _run_json(self, cmd, allow_not_found=False):
        out = self._run(cmd, allow_not_found=allow_not_found)

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
                 internal=None, use_jump_host=True):
        self.oc_map = {}
        self.calling_integration = integration
        self.calling_e2e_test = e2e_test
        self.settings = settings
        self.internal = internal
        self.use_jump_host = use_jump_host

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
            if self.use_jump_host:
                jump_host = cluster_info.get('jumpHost')
            else:
                jump_host = None
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
