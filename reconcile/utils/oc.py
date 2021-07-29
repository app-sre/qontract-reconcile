import copy
import json
import logging
import os
import tempfile
import time
from datetime import datetime
from functools import wraps
from subprocess import Popen, PIPE
from threading import Lock

import urllib3

from sretoolbox.utils import retry
from prometheus_client import Counter

from kubernetes.client import Configuration, ApiClient
from kubernetes.client.exceptions import ApiException

from reconcile.utils.metrics import reconcile_time
from reconcile.status import RunningState
from reconcile.utils.jump_host import JumpHostSSH
from reconcile.utils.secret_reader import SecretReader
import reconcile.utils.threaded as threaded
from openshift.dynamic.exceptions import NotFoundError
from openshift.dynamic import DynamicClient
from reconcile.utils.unleash import (get_feature_toggle_strategies,
                                     get_feature_toggle_state)
from openshift.dynamic.resource import ResourceList

urllib3.disable_warnings()


class StatusCodeError(Exception):
    pass


class InvalidValueApplyError(Exception):
    pass


class FieldIsImmutableError(Exception):
    pass


class MayNotChangeOnceSetError(Exception):
    pass


class PrimaryClusterIPCanNotBeUnsetError(Exception):
    pass


class MetaDataAnnotationsTooLongApplyError(Exception):
    pass


class UnsupportedMediaTypeError(Exception):
    pass


class StatefulSetUpdateForbidden(Exception):
    pass


class NoOutputError(Exception):
    pass


class JSONParsingError(Exception):
    pass


class RecyclePodsUnsupportedKindError(Exception):
    pass


class RecyclePodsInvalidAnnotationValue(Exception):
    pass


class PodNotReadyError(Exception):
    pass


class JobNotRunningError(Exception):
    pass


class OCDecorators:
    @classmethod
    def process_reconcile_time(cls, function):
        '''
        Compare current time against bundle commit time and create log
        and metrics from it.

        This decorator expects an OCProcessReconcileTimeDecoratorMsg
        object as the only or last element of the decorated function's return
        value.

        Metrics are generated if the resource doesn't have the
        qontract.ignore_reconcile_time annotation.

        Log message is created if the following conditions are met:

        * Decorator msg is_log_slow_oc_reconcile is true. This value should
          come from LOG_SLOW_OC_RECONCILE env variable
        * Decorator msg slow_oc_reconcile_threshold is less than the time
          elapsed since the bundle commit timestamp. This value should come
          from SLOW_OC_RECONCILE_THRESHOLD
        '''

        @wraps(function)
        def wrapper(*args, **kwargs):
            result = function(*args, **kwargs)
            msg = result[:-1] if isinstance(result, (list, tuple)) else result

            if not isinstance(msg, OCProcessReconcileTimeDecoratorMsg):
                return result

            running_state = RunningState()
            commit_time = float(running_state.timestamp)
            time_spent = time.time() - commit_time

            try:
                resource_kind = msg.resource['kind']
                resource_name = msg.resource['metadata']['name']
                annotations = \
                    msg.resource['metadata'].get('annotations', {})
            except KeyError as e:
                logging.warning(f'Error processing metric: {e}')
                return result

            function_name = f'{function.__module__}.{function.__qualname__}'
            ignore_reconcile_time = \
                annotations.get('qontract.ignore_reconcile_time') == 'true'
            if not ignore_reconcile_time:
                reconcile_time.labels(
                    name=function_name,
                    integration=running_state.integration
                ).observe(amount=time_spent)

            if not msg.is_log_slow_oc_reconcile:
                return result

            if time_spent > msg.slow_oc_reconcile_threshold:
                log_msg = f'Action {function_name} for {resource_kind} ' \
                          f'{resource_name} in namespace ' \
                          f'{msg.namespace} from ' \
                          f'{msg.server} took {time_spent} to ' \
                          f'reconcile. Commit sha {running_state.commit} ' \
                          f'and commit ts {running_state.timestamp}.'

                if ignore_reconcile_time:
                    log_msg += ' Ignored in the metric published.'

                logging.info(log_msg)

            return result

        return wrapper


class OCProcessReconcileTimeDecoratorMsg:
    def __init__(self, namespace, resource, server,
                 slow_oc_reconcile_threshold, is_log_slow_oc_reconcile):
        self.namespace = namespace
        self.resource = resource
        self.server = server
        self.slow_oc_reconcile_threshold = slow_oc_reconcile_threshold
        self.is_log_slow_oc_reconcile = is_log_slow_oc_reconcile


class OCDeprecated:
    def __init__(self, cluster_name, server, token, jh=None, settings=None,
                 init_projects=False, init_api_resources=False,
                 local=False):
        """Initiates an OC client

        Args:
            cluster_name (string): Name of cluster
            server (string): Server URL of the cluster
            token (string): Token to use for authentication
            jh (dict, optional): Info to initiate JumpHostSSH
            settings (dict, optional): App-interface settings
            init_projects (bool, optional): Initiate projects
            init_api_resources (bool, optional): Initiate api-resources
            local (bool, optional): Use oc locally
        """
        self.cluster_name = cluster_name
        self.server = server
        oc_base_cmd = [
            'oc',
            '--kubeconfig', '/dev/null'
        ]
        if server:
            oc_base_cmd.extend(['--server', server])

        if token:
            oc_base_cmd.extend(['--token', token])

        self.jump_host = None
        if jh is not None:
            self.jump_host = JumpHostSSH(jh, settings=settings)
            oc_base_cmd = self.jump_host.get_ssh_base_cmd() + oc_base_cmd

        self.oc_base_cmd = oc_base_cmd

        # calling get_version to check if cluster is reachable
        if not local:
            self.get_version()
        self.init_projects = init_projects
        if self.init_projects:
            self.projects = \
                [p['metadata']['name']
                 for p
                 in self.get_all('Project.project.openshift.io')['items']]
        self.init_api_resources = init_api_resources
        if self.init_api_resources:
            self.api_resources = self.get_api_resources()
        else:
            self.api_resources = None

        self.slow_oc_reconcile_threshold = \
            float(os.environ.get('SLOW_OC_RECONCILE_THRESHOLD', 600))

        self.is_log_slow_oc_reconcile = \
            os.environ.get('LOG_SLOW_OC_RECONCILE', '').lower() \
            in ['true', 'yes']

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

    def get(self, namespace, kind, name=None, allow_not_found=False):
        cmd = ['get', '-o', 'json', kind]
        if name:
            cmd.append(name)
        if namespace is not None:
            cmd.extend(['-n', namespace])
        return self._run_json(cmd, allow_not_found=allow_not_found)

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

    def remove_last_applied_configuration(self, namespace, kind, name):
        cmd = ['annotate', '-n', namespace, kind, name,
               'kubectl.kubernetes.io/last-applied-configuration-']
        self._run(cmd)

    def _msg_to_process_reconcile_time(self, namespace, resource):
        return OCProcessReconcileTimeDecoratorMsg(
            namespace=namespace,
            resource=resource,
            server=self.server,
            slow_oc_reconcile_threshold=self.slow_oc_reconcile_threshold,
            is_log_slow_oc_reconcile=self.is_log_slow_oc_reconcile)

    @OCDecorators.process_reconcile_time
    def apply(self, namespace, resource):
        cmd = ['apply', '-n', namespace, '-f', '-']
        self._run(cmd, stdin=resource.toJSON(), apply=True)
        return self._msg_to_process_reconcile_time(namespace, resource.body)

    @OCDecorators.process_reconcile_time
    def create(self, namespace, resource):
        cmd = ['create', '-n', namespace, '-f', '-']
        self._run(cmd, stdin=resource.toJSON(), apply=True)
        return self._msg_to_process_reconcile_time(namespace, resource.body)

    @OCDecorators.process_reconcile_time
    def replace(self, namespace, resource):
        cmd = ['replace', '-n', namespace, '-f', '-']
        self._run(cmd, stdin=resource.toJSON(), apply=True)
        return self._msg_to_process_reconcile_time(namespace, resource.body)

    @OCDecorators.process_reconcile_time
    def delete(self, namespace, kind, name, cascade=True):
        cmd = ['delete', '-n', namespace, kind, name,
               f'--cascade={str(cascade).lower()}']
        self._run(cmd)
        resource = {'kind': kind, 'metadata': {'name': name}}
        return self._msg_to_process_reconcile_time(namespace, resource)

    def project_exists(self, name):
        if self.init_projects:
            return name in self.projects

        try:
            self.get(None, 'Project.project.openshift.io', name)
        except StatusCodeError as e:
            if 'NotFound' in str(e):
                return False
            else:
                raise e
        return True

    @OCDecorators.process_reconcile_time
    def new_project(self, namespace):
        cmd = ['new-project', namespace]
        try:
            self._run(cmd)
        except StatusCodeError as e:
            if 'AlreadyExists' not in str(e):
                raise e

        # This return will be removed by the last decorator
        resource = {'kind': 'Namespace', 'metadata': {'name': namespace}}
        return self._msg_to_process_reconcile_time(namespace, resource)

    @OCDecorators.process_reconcile_time
    def delete_project(self, namespace):
        cmd = ['delete', 'project', namespace]
        self._run(cmd)

        # This return will be removed by the last decorator
        resource = {'kind': 'Namespace', 'metadata': {'name': namespace}}
        return self._msg_to_process_reconcile_time(namespace, resource)

    def get_group_if_exists(self, name):
        try:
            return self.get(None, 'Group', name)
        except StatusCodeError as e:
            if 'NotFound' in str(e):
                return None
            else:
                raise e

    def create_group(self, group):
        if self.get_group_if_exists(group) is not None:
            return
        cmd = ['adm', 'groups', 'new', group]
        self._run(cmd)

    def release_mirror(self, from_release, to, to_release, dockerconfig):
        with tempfile.NamedTemporaryFile() as fp:
            content = json.dumps(dockerconfig)
            fp.write(content.encode())
            fp.seek(0)

            cmd = [
                'adm',
                '--registry-config', fp.name,
                'release', 'mirror',
                '--from', from_release,
                '--to', to,
                '--to-release-image', to_release,
                '--max-per-registry', '1'
            ]

            self._run(cmd)

    def delete_group(self, group):
        cmd = ['delete', 'group', group]
        self._run(cmd)

    def get_users(self):
        return self.get_all('User')['items']

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

    def get_api_resources(self):
        # oc api-resources only has name or wide output
        # and we need to get the KIND, which is the last column
        cmd = ['api-resources', '--no-headers']
        results = self._run(cmd).decode('utf-8').split('\n')
        return [r.split()[-1] for r in results]

    def get_version(self):
        # this is actually a 10 second timeout, because: oc reasons
        cmd = ['version', '--request-timeout=5']
        return self._run(cmd)

    @retry(exceptions=(JobNotRunningError), max_attempts=20)
    def wait_for_job_running(self, namespace, name):
        logging.info('waiting for job to run: ' + name)
        pods = self.get_items('Pod', namespace=namespace,
                              labels={'job-name': name})

        ready_pods = [pod for pod in pods
                      if pod['status'].get('phase')
                      in ('Running', 'Succeeded')]

        if not ready_pods:
            raise JobNotRunningError(name)

    def job_logs(self, namespace, name, follow, output):
        self.wait_for_job_running(namespace, name)
        cmd = ['logs', '-n', namespace, f'job/{name}']
        if follow:
            cmd.append('-f')
        output_file = open(os.path.join(output, name), 'w')
        # collect logs to file async
        Popen(self.oc_base_cmd + cmd, stdout=output_file)

    @staticmethod
    def get_service_account_username(user):
        namespace = user.split('/')[0]
        name = user.split('/')[1]
        return "system:serviceaccount:{}:{}".format(namespace, name)

    def get_owned_pods(self, namespace, resource):
        pods = self.get(namespace, 'Pod')['items']
        owned_pods = []
        for p in pods:
            owner = self.get_obj_root_owner(namespace, p)
            if (resource.kind, resource.name) == \
                    (owner['kind'], owner['metadata']['name']):
                owned_pods.append(p)

        return owned_pods

    def recycle_orphan_pods(self, namespace, pods):
        for p in pods:
            name = p['metadata']['name']
            self.delete(namespace, 'Pod', name)
            self.validate_pod_ready(namespace, name)

    @retry(max_attempts=20)
    def validate_pod_ready(self, namespace, name):
        logging.info([self.validate_pod_ready.__name__,
                      self.cluster_name, namespace, name])
        pod = self.get(namespace, 'Pod', name)
        for status in pod['status']['containerStatuses']:
            if not status['ready']:
                raise PodNotReadyError(name)

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
                           self.cluster_name, namespace, dep_kind])
            return

        dep_annotations = dep_resource.body['metadata'].get('annotations', {})
        qontract_recycle = dep_annotations.get('qontract.recycle')
        if qontract_recycle is True:
            raise RecyclePodsInvalidAnnotationValue('should be "true"')
        if qontract_recycle != 'true':
            logging.debug(['skipping_pod_recycle_no_annotation',
                           self.cluster_name, namespace, dep_kind])
            return

        dep_name = dep_resource.name
        pods = self.get(namespace, 'Pod')['items']

        if dep_kind == 'Secret':
            pods_to_recycle = [pod for pod in pods
                               if self.secret_used_in_pod(dep_name, pod)]
        elif dep_kind == 'ConfigMap':
            pods_to_recycle = [pod for pod in pods
                               if self.configmap_used_in_pod(dep_name, pod)]
        else:
            raise RecyclePodsUnsupportedKindError(dep_kind)

        recyclables = {}
        supported_recyclables = [
            'Deployment',
            'DeploymentConfig',
            'StatefulSet',
            'DaemonSet',
        ]
        for pod in pods_to_recycle:
            owner = self.get_obj_root_owner(namespace, pod,
                                            allow_not_found=True)
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
                logging.info([f'recycle_{kind.lower()}',
                              self.cluster_name, namespace, name])
                if not dry_run:
                    now = datetime.now()
                    recycle_time = now.strftime("%d/%m/%Y %H:%M:%S")

                    # honor update strategy by setting annotations to force
                    # a new rollout
                    a = obj['spec']['template']['metadata'].get(
                        'annotations', {})
                    a['recycle.time'] = recycle_time
                    obj['spec']['template']['metadata']['annotations'] = a
                    cmd = ['apply', '-n', namespace, '-f', '-']
                    stdin = json.dumps(obj, sort_keys=True)
                    self._run(cmd, stdin=stdin, apply=True)

    def get_obj_root_owner(self, ns, obj, allow_not_found=False):
        """Get object root owner (recursively find the top level owner).
        - Returns obj if it has no ownerReferences
        - Returns obj if all ownerReferences have controller set to false
        - Returns obj if controller is true, allow_not_found is true,
          but referenced object does not exist
        - Throws an exception if controller is true, allow_not_found false,
          but referenced object does not exist
        - Recurses if controller is true and referenced object exists

        Args:
            ns (string): namespace of the object
            obj (dict): representation of the object
            allow_not_found (bool, optional): allow owner to be not found

        Returns:
            dict: representation of the object's owner
        """
        refs = obj['metadata'].get('ownerReferences', [])
        for r in refs:
            if r.get('controller'):
                controller_obj = self.get(
                    ns, r['kind'], r['name'],
                    allow_not_found=allow_not_found)
                if controller_obj:
                    return self.get_obj_root_owner(
                        ns,
                        controller_obj,
                        allow_not_found=allow_not_found
                    )
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

    @retry(exceptions=(StatusCodeError, NoOutputError), max_attempts=10)
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
            if kwargs.get('apply'):
                if 'Invalid value: 0x0' in err:
                    raise InvalidValueApplyError(f"[{self.server}]: {err}")
                if 'Invalid value: ' in err:
                    if ': field is immutable' in err:
                        raise FieldIsImmutableError(f"[{self.server}]: {err}")
                    if ': may not change once set' in err:
                        raise MayNotChangeOnceSetError(
                            f"[{self.server}]: {err}")
                    if ': primary clusterIP can not be unset' in err:
                        raise PrimaryClusterIPCanNotBeUnsetError(
                            f"[{self.server}]: {err}")
                if 'metadata.annotations: Too long' in err:
                    raise MetaDataAnnotationsTooLongApplyError(
                        f"[{self.server}]: {err}")
                if 'UnsupportedMediaType' in err:
                    raise UnsupportedMediaTypeError(f"[{self.server}]: {err}")
                if 'updates to statefulset spec for fields other than' in err:
                    raise StatefulSetUpdateForbidden(f"[{self.server}]: {err}")
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


class OCNative(OCDeprecated):
    def __init__(self, cluster_name, server, token, jh=None, settings=None,
                 init_projects=False, init_api_resources=False,
                 local=False):
        super().__init__(cluster_name, server, token, jh, settings,
                         init_projects=False, init_api_resources=False,
                         local=local)
        if server:
            self.client = self._get_client(server, token)
            self.api_kind_version = self.get_api_resources()
        else:
            init_api_resources = False
            init_projects = False

        self.object_clients = {}
        self.init_projects = init_projects
        if self.init_projects:
            self.projects = \
                [p['metadata']['name']
                 for p
                 in self.get_all('Project.project.openshift.io')['items']]
        self.init_api_resources = init_api_resources
        if self.init_api_resources:
            self.api_resources = self.api_kind_version.keys()
        else:
            self.api_resources = None

    def _get_client(self, server, token):
        opts = dict(
            api_key={'authorization': f'Bearer {token}'},
            host=server,
            verify_ssl=False,
            # default timeout seems to be 1+ minutes
            retries=5
        )

        if self.jump_host:
            # the ports could be parameterized, but at this point
            # we only have need of 1 tunnel for 1 service
            self.jump_host.create_ssh_tunnel(8888, 8888)
            opts['proxy'] = 'http://localhost:8888'

        configuration = Configuration()

        # the kubernetes client configuration takes a limited set
        # of parameters during initialization, but there are a lot
        # more options that can be set to tweak the behavior of the
        # client via instance variables.  We define a set of options
        # above in the format of var_name:value then set them here
        # in the configuration object with setattr.
        for k, v in opts.items():
            setattr(configuration, k, v)

        k8s_client = ApiClient(configuration)
        try:
            return DynamicClient(k8s_client)
        except urllib3.exceptions.MaxRetryError as e:
            raise StatusCodeError(f"[{self.server}]: {e}")

    def _get_obj_client(self, kind, group_version):
        key = f'{kind}.{group_version}'
        if key not in self.object_clients:
            self.object_clients[key] = self.client.resources.get(
                api_version=group_version, kind=kind)
        return self.object_clients[key]

    def _parse_kind(self, kind_name):
        kind_group = kind_name.split('.', 1)
        kind = kind_group[0]
        if kind in self.api_kind_version:
            group_version = self.api_kind_version[kind][0]
        else:
            raise StatusCodeError(f'{self.server}: {kind} does not exist')

        # if a kind_group has more than 1 entry than the kind_name is in
        # the format kind.apigroup.  Find the apigroup/version that matches
        # the apigroup passed with the kind_name
        if len(kind_group) > 1:
            apigroup_override = kind_group[1]
            find = False
            for gv in self.api_kind_version[kind]:
                if apigroup_override in gv:
                    group_version = gv
                    find = True
                    break
            if not find:
                raise StatusCodeError(f'{self.server}: {apigroup_override}'
                                      f' does not have kind {kind}')
        return(kind, group_version)

    # this function returns a kind:apigroup/version map for each kind on the
    # cluster
    def get_api_resources(self):
        c_res = self.client.resources
        # this returns a prefix:apis map
        api_prefix = c_res.parse_api_groups(
            request_resources=False, update=True)
        kind_groupversion = {}
        for prefix, apis in api_prefix.items():
            # each api prefix consists of api:versions map
            for apigroup, versions in apis.items():
                if prefix == 'apis' and len(apigroup) == 0:
                    # the apis group has an entry with an empty api, but
                    # querying the apis group with a blank api produces an
                    # error.  We skip that condition with this hack
                    continue
                # each version is a version:obj map, where obj contains if this
                # api version is preferred and optionally a list of kinds that
                # are part of that apigroup/version.
                for version, obj in versions.items():
                    try:
                        resources = c_res.get_resources_for_api_version(
                            prefix, apigroup, version, True)
                    except ApiException:
                        # there may be apigroups/versions that require elevated
                        # permisions, so go to the next one
                        next
                    # resources is a map containing kind:Resource and
                    # {kind}List:ResourceList where a Resource contains the api
                    # group_version (group/api_version) and a ResourceList
                    # represents a list of API objects
                    for kind, res in resources.items():
                        for r in res:
                            if isinstance(r, ResourceList):
                                continue
                            # add the kind and apigroup/version to the set
                            # of api kinds
                            kind_groupversion = self.add_group_kind(
                                kind, kind_groupversion,
                                r.group_version, obj.preferred)
        return kind_groupversion

    def get_items(self, kind, **kwargs):
        k, group_version = self._parse_kind(kind)
        obj_client = self._get_obj_client(group_version=group_version, kind=k)

        namespace = ''
        if 'namespace' in kwargs:
            namespace = kwargs['namespace']
            # for cluster scoped integrations
            # currently only openshift-clusterrolebindings
            if namespace != 'cluster':
                if not self.project_exists(namespace):
                    return []

        labels = ''
        if 'labels' in kwargs:
            labels_list = [
                "{}={}".format(k, v)
                for k, v in kwargs.get('labels').items()
            ]

            labels = ','.join(labels_list)

        resource_names = kwargs.get('resource_names')
        if resource_names:
            items = []
            for resource_name in resource_names:
                try:
                    item = obj_client.get(
                        name=resource_name, namespace=namespace,
                        label_selector=labels)
                    if item:
                        items.append(item.to_dict())
                except NotFoundError:
                    pass
            items_list = {'items': items}
        else:
            items_list = obj_client.get(
                namespace=namespace, label_selector=labels).to_dict()

        items = items_list.get('items')
        if items is None:
            raise Exception("Expecting items")

        return items

    def get(self, namespace, kind, name=None, allow_not_found=False):
        k, group_version = self._parse_kind(kind)
        obj_client = self._get_obj_client(group_version=group_version, kind=k)
        try:
            obj = obj_client.get(name=name, namespace=namespace)
            return obj.to_dict()
        except NotFoundError as e:
            if allow_not_found:
                return {}
            else:
                raise StatusCodeError(f"[{self.server}]: {e}")

    def get_all(self, kind, all_namespaces=False):
        k, group_version = self._parse_kind(kind)
        obj_client = self._get_obj_client(
            group_version=group_version, kind=k)
        try:
            return obj_client.get().to_dict()
        except NotFoundError as e:
            raise StatusCodeError(f"[{self.server}]: {e}")

    @staticmethod
    def add_group_kind(kind, kgv, new, preferred):
        updated_kgv = copy.copy(kgv)
        if kind not in kgv:
            # this is a new kind so add it
            updated_kgv[kind] = [new]
        else:
            # this kind already exists, so check if this apigroup has
            # already been added as an option.  If this apigroup/version is the
            # preferred one, then replace the apigroup/version so that the
            # preferred apigroup/version is used instead of a non-preferred one
            group = new.split('/', 1)[0]
            new_group = True
            for pos in range(len(kgv[kind])):
                if group in kgv[kind][pos]:
                    new_group = False
                    if preferred:
                        updated_kgv[kind][pos] = new
                    break

            if new_group:
                # this is a new apigroup
                updated_kgv[kind].append(new)
        return updated_kgv


class OC:
    client_status = Counter(name='qontract_reconcile_native_client',
                            documentation='Cluster is using openshift '
                            'native client',
                            labelnames=['cluster_name', 'native_client'])

    def __new__(cls, cluster_name, server, token, jh=None, settings=None,
                init_projects=False, init_api_resources=False,
                local=False):
        use_native = os.environ.get('USE_NATIVE_CLIENT', '')
        if len(use_native) > 0:
            use_native = use_native.lower() in ['true', 'yes']
        else:
            enable_toggle = 'openshift-resources-native-client'
            strategies = get_feature_toggle_strategies(
                enable_toggle, ['perCluster'])

            # only use the native client if the toggle is enabled and this
            # server is listed in the perCluster strategy
            cluster_in_strategy = False
            if strategies:
                for s in strategies:
                    if cluster_name in s.parameters['cluster_name'].split(','):
                        cluster_in_strategy = True
                        break
            use_native = get_feature_toggle_state(enable_toggle) and \
                cluster_in_strategy

        if use_native:
            OC.client_status.labels(
                cluster_name=cluster_name, native_client=True).inc()
            return OCNative(cluster_name, server, token, jh, settings,
                            init_projects, init_api_resources,
                            local)
        else:
            OC.client_status.labels(
                cluster_name=cluster_name, native_client=False).inc()
            return OCDeprecated(cluster_name, server, token, jh, settings,
                                init_projects, init_api_resources,
                                local)


class OC_Map:
    """OC_Map gets a GraphQL query results list as input
    and initiates a dictionary of OC clients per cluster.

    The input must contain either 'clusters' or 'namespaces', but not both.

    In case a cluster does not have an automation token
    the OC client will be initiated to False.
    """

    def __init__(self, clusters=None, namespaces=None,
                 integration='', e2e_test='', settings=None,
                 internal=None, use_jump_host=True, thread_pool_size=1,
                 init_projects=False, init_api_resources=False,
                 cluster_admin=False):
        self.oc_map = {}
        self.calling_integration = integration
        self.calling_e2e_test = e2e_test
        self.settings = settings
        self.internal = internal
        self.use_jump_host = use_jump_host
        self.thread_pool_size = thread_pool_size
        self.init_projects = init_projects
        self.init_api_resources = init_api_resources
        self._lock = Lock()

        if clusters and namespaces:
            raise KeyError('expected only one of clusters or namespaces.')
        elif clusters:
            threaded.run(self.init_oc_client, clusters, self.thread_pool_size,
                         cluster_admin=cluster_admin)
        elif namespaces:
            clusters = [ns_info['cluster'] for ns_info in namespaces]
            threaded.run(self.init_oc_client, clusters, self.thread_pool_size,
                         cluster_admin=cluster_admin)
        else:
            raise KeyError('expected one of clusters or namespaces.')

    def init_oc_client(self, cluster_info, cluster_admin):
        cluster = cluster_info['name']
        if self.oc_map.get(cluster):
            return None
        if self.cluster_disabled(cluster_info):
            return None
        if self.internal is not None:
            # integration is executed with `--internal` or `--external`
            # filter out non matching clusters
            if self.internal and not cluster_info['internal']:
                return
            if not self.internal and cluster_info['internal']:
                return

        if cluster_admin:
            automation_token = cluster_info.get('clusterAdminAutomationToken')
        else:
            automation_token = cluster_info.get('automationToken')
        if automation_token is None:
            self.set_oc(cluster,
                        OCLogMsg(log_level=logging.ERROR,
                                 message=f"[{cluster}]"
                                 " has no automation token"))
        else:
            server_url = cluster_info['serverUrl']
            secret_reader = SecretReader(settings=self.settings)
            token = secret_reader.read(automation_token)
            if self.use_jump_host:
                jump_host = cluster_info.get('jumpHost')
            else:
                jump_host = None
            try:
                oc_client = OC(cluster, server_url, token, jump_host,
                               settings=self.settings,
                               init_projects=self.init_projects,
                               init_api_resources=self.init_api_resources)
                self.set_oc(cluster, oc_client)
            except StatusCodeError as e:
                self.set_oc(cluster,
                            OCLogMsg(log_level=logging.ERROR,
                                     message=f"[{cluster}]"
                                     f" is unreachable: {e}"))

    def set_oc(self, cluster, value):
        with self._lock:
            self.oc_map[cluster] = value

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
        return self.oc_map.get(cluster,
                               OCLogMsg(log_level=logging.DEBUG,
                                        message=f"[{cluster}]"
                                        " cluster skipped"))

    def clusters(self):
        return [k for k, v in self.oc_map.items() if v]

    def cleanup(self):
        for oc in self.oc_map.values():
            if oc:
                oc.cleanup()


class OCLogMsg:
    def __init__(self, log_level, message):
        self.log_level = log_level
        self.message = message

    def __bool__(self):
        return False
