import copy
import json
import logging
import os
import re
import tempfile
import threading
import time
from collections.abc import (
    Iterable,
    Mapping,
)
from contextlib import suppress
from datetime import datetime
from functools import wraps
from subprocess import (
    PIPE,
    Popen,
)
from threading import Lock
from typing import (
    Any,
    Optional,
    Union,
)

import urllib3
from kubernetes.client import (
    ApiClient,
    Configuration,
)
from kubernetes.client.exceptions import ApiException
from kubernetes.dynamic.client import DynamicClient
from kubernetes.dynamic.discovery import (
    LazyDiscoverer,
    ResourceGroup,
)
from kubernetes.dynamic.exceptions import (
    ForbiddenError,
    InternalServerError,
    NotFoundError,
    ResourceNotFoundError,
    ResourceNotUniqueError,
    ServerTimeoutError,
)
from kubernetes.dynamic.resource import ResourceList
from prometheus_client import Counter
from sretoolbox.utils import (
    retry,
    threaded,
)

from reconcile.status import RunningState
from reconcile.utils.jump_host import (
    JumphostParameters,
    JumpHostSSH,
)
from reconcile.utils.metrics import reconcile_time
from reconcile.utils.oc_connection_parameters import OCConnectionParameters
from reconcile.utils.secret_reader import (
    SecretNotFound,
    SecretReader,
)
from reconcile.utils.unleash import get_feature_toggle_state

urllib3.disable_warnings()

GET_REPLICASET_MAX_ATTEMPTS = 20


class StatusCodeError(Exception):
    pass


class InvalidValueApplyError(Exception):
    pass


class FieldIsImmutableError(Exception):
    pass


class DeploymentFieldIsImmutableError(Exception):
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


class ObjectHasBeenModifiedError(Exception):
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
        """
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
        """

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
                resource_kind = msg.resource["kind"]
                resource_name = msg.resource["metadata"]["name"]
                annotations = msg.resource["metadata"].get("annotations", {})
            except KeyError as e:
                logging.warning(f"Error processing metric: {e}")
                return result

            function_name = f"{function.__module__}.{function.__qualname__}"
            ignore_reconcile_time = (
                annotations.get("qontract.ignore_reconcile_time") == "true"
            )
            if not ignore_reconcile_time:
                reconcile_time.labels(
                    name=function_name, integration=running_state.integration
                ).observe(amount=time_spent)

            if not msg.is_log_slow_oc_reconcile:
                return result

            if time_spent > msg.slow_oc_reconcile_threshold:
                log_msg = (
                    f"Action {function_name} for {resource_kind} "
                    f"{resource_name} in namespace "
                    f"{msg.namespace} from "
                    f"{msg.server} took {time_spent} to "
                    f"reconcile. Commit sha {running_state.commit} "
                    f"and commit ts {running_state.timestamp}."
                )

                if ignore_reconcile_time:
                    log_msg += " Ignored in the metric published."

                logging.info(log_msg)

            return result

        return wrapper


class OCProcessReconcileTimeDecoratorMsg:
    def __init__(
        self,
        namespace,
        resource,
        server,
        slow_oc_reconcile_threshold,
        is_log_slow_oc_reconcile,
    ):
        self.namespace = namespace
        self.resource = resource
        self.server = server
        self.slow_oc_reconcile_threshold = slow_oc_reconcile_threshold
        self.is_log_slow_oc_reconcile = is_log_slow_oc_reconcile


def oc_process(template, parameters=None):
    oc = OCLocal(cluster_name="cluster", server=None, token=None, local=True)
    return oc.process(template, parameters)


def equal_spec_template(t1: dict, t2: dict) -> bool:
    """Compare two spec.templates."""
    t1_copy = copy.deepcopy(t1)
    t2_copy = copy.deepcopy(t2)
    try:
        del t1_copy["metadata"]["labels"]["pod-template-hash"]
    except KeyError:
        pass
    try:
        del t2_copy["metadata"]["labels"]["pod-template-hash"]
    except KeyError:
        pass
    return t1_copy == t2_copy


class OCDeprecated:  # pylint: disable=too-many-public-methods
    def __init__(
        self,
        cluster_name: Optional[str],
        server: Optional[str],
        token: Optional[str],
        jh: Optional[Mapping[Any, Any]] = None,
        settings: Optional[Mapping[Any, Any]] = None,
        init_projects: bool = False,
        init_api_resources: bool = False,
        local: bool = False,
        insecure_skip_tls_verify: bool = False,
        connection_parameters: Optional[OCConnectionParameters] = None,
    ):
        """
        As of now we have to conform with 2 ways to initialize this client:

        1. Old way with nested untyped dictionaries
        2. Typed way with connection_parameters

        We aim to deprecate the old way (w/o connection_parameters) over time.
        """
        if connection_parameters:
            self._init(
                connection_parameters=connection_parameters,
                local=local,
                init_projects=init_projects,
                init_api_resources=init_api_resources,
            )
        elif cluster_name:
            self._init_old_without_types(
                cluster_name=cluster_name,
                server=server,
                token=token,
                jh=jh,
                settings=settings,
                init_projects=init_projects,
                init_api_resources=init_api_resources,
                local=local,
                insecure_skip_tls_verify=insecure_skip_tls_verify,
            )

    def _init_old_without_types(
        self,
        cluster_name: str,
        server: Optional[str],
        token: Optional[str],
        jh: Optional[Mapping[Any, Any]] = None,
        settings: Optional[Mapping[Any, Any]] = None,
        init_projects: bool = False,
        init_api_resources: bool = False,
        local: bool = False,
        insecure_skip_tls_verify: bool = False,
    ):
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
        oc_base_cmd = ["oc", "--kubeconfig", "/dev/null"]
        if insecure_skip_tls_verify:
            oc_base_cmd.extend(["--insecure-skip-tls-verify"])
        if server:
            oc_base_cmd.extend(["--server", server])

        if token:
            oc_base_cmd.extend(["--token", token])

        self.jump_host = None
        if jh is not None:
            secret_reader = SecretReader(settings=settings)
            key = secret_reader.read(jh["identity"])
            jumphost_parameters = JumphostParameters(
                hostname=jh["hostname"],
                key=key,
                known_hosts=jh["knownHosts"],
                local_port=jh.get("localPort"),
                port=jh.get("port"),
                remote_port=jh.get("remotePort"),
                user=jh["user"],
            )
            self.jump_host = JumpHostSSH(parameters=jumphost_parameters)
            oc_base_cmd = self.jump_host.get_ssh_base_cmd() + oc_base_cmd

        self.oc_base_cmd = oc_base_cmd

        # calling get_version to check if cluster is reachable
        if not local:
            self.get_version()

        self.api_resources_lock = threading.RLock()
        self.init_api_resources = init_api_resources
        self.api_resources = None
        if self.init_api_resources:
            self.api_resources = self.get_api_resources()

        self.init_projects = init_projects
        if self.init_projects:
            if self.is_kind_supported("Project"):
                kind = "Project.project.openshift.io"
            else:
                kind = "Namespace"
            self.projects = [p["metadata"]["name"] for p in self.get_all(kind)["items"]]

        self.slow_oc_reconcile_threshold = float(
            os.environ.get("SLOW_OC_RECONCILE_THRESHOLD", 600)
        )

        self.is_log_slow_oc_reconcile = os.environ.get(
            "LOG_SLOW_OC_RECONCILE", ""
        ).lower() in ["true", "yes"]

    def _init(
        self,
        connection_parameters: OCConnectionParameters,
        init_projects: bool = False,
        init_api_resources: bool = False,
        local: bool = False,
    ):
        self.cluster_name = connection_parameters.cluster_name
        self.server = connection_parameters.server_url
        oc_base_cmd = ["oc", "--kubeconfig", "/dev/null"]
        if connection_parameters.skip_tls_verify:
            oc_base_cmd.extend(["--insecure-skip-tls-verify"])
        if self.server:
            oc_base_cmd.extend(["--server", self.server])

        token = connection_parameters.automation_token
        if (
            connection_parameters.is_cluster_admin
            and connection_parameters.cluster_admin_automation_token
        ):
            token = connection_parameters.cluster_admin_automation_token

        if token:
            oc_base_cmd.extend(["--token", token])

        self.jump_host = None
        if (
            connection_parameters.jumphost_hostname
            and connection_parameters.jumphost_user
            and connection_parameters.jumphost_key
            and connection_parameters.jumphost_known_hosts
        ):
            jumphost_parameters = JumphostParameters(
                hostname=connection_parameters.jumphost_hostname,
                key=connection_parameters.jumphost_key,
                known_hosts=connection_parameters.jumphost_known_hosts,
                local_port=connection_parameters.jumphost_local_port,
                port=connection_parameters.jumphost_port,
                remote_port=connection_parameters.jumphost_remote_port,
                user=connection_parameters.jumphost_user,
            )
            self.jump_host = JumpHostSSH(parameters=jumphost_parameters)
            oc_base_cmd = self.jump_host.get_ssh_base_cmd() + oc_base_cmd

        self.oc_base_cmd = oc_base_cmd

        # calling get_version to check if cluster is reachable
        if not local:
            self.get_version()

        self.api_resources_lock = threading.RLock()
        self.init_api_resources = init_api_resources
        self.api_resources = None
        if self.init_api_resources:
            self.api_resources = self.get_api_resources()

        self.init_projects = init_projects
        if self.init_projects:
            if self.is_kind_supported("Project"):
                kind = "Project.project.openshift.io"
            else:
                kind = "Namespace"
            self.projects = [p["metadata"]["name"] for p in self.get_all(kind)["items"]]

        self.slow_oc_reconcile_threshold = float(
            os.environ.get("SLOW_OC_RECONCILE_THRESHOLD", 600)
        )

        self.is_log_slow_oc_reconcile = os.environ.get(
            "LOG_SLOW_OC_RECONCILE", ""
        ).lower() in ["true", "yes"]

    def whoami(self):
        return self._run(["whoami"])

    def cleanup(self):
        if hasattr(self, "jump_host") and isinstance(self.jump_host, JumpHostSSH):
            self.jump_host.cleanup()

    def get_items(self, kind, **kwargs):
        cmd = ["get", kind, "-o", "json"]

        if "namespace" in kwargs:
            namespace = kwargs["namespace"]
            # for cluster scoped integrations
            # currently only openshift-clusterrolebindings
            if namespace != "cluster":
                if not self.project_exists(namespace):
                    return []
                cmd.extend(["-n", namespace])

        if "labels" in kwargs:
            labels_list = [
                "{}={}".format(k, v) for k, v in kwargs.get("labels").items()
            ]

            cmd.append("-l")
            cmd.append(",".join(labels_list))

        resource_names = kwargs.get("resource_names")
        if resource_names:
            items = []
            for resource_name in resource_names:
                resource_cmd = cmd + [resource_name]
                item = self._run_json(resource_cmd, allow_not_found=True)
                if item:
                    items.append(item)
            items_list = {"items": items}
        else:
            items_list = self._run_json(cmd)

        items = items_list.get("items")
        if items is None:
            raise Exception("Expecting items")

        return items

    def get(self, namespace, kind, name=None, allow_not_found=False):
        cmd = ["get", "-o", "json", kind]
        if name:
            cmd.append(name)
        if namespace is not None:
            cmd.extend(["-n", namespace])
        return self._run_json(cmd, allow_not_found=allow_not_found)

    def get_all(self, kind, all_namespaces=False):
        cmd = ["get", "-o", "json", kind]
        if all_namespaces:
            cmd.append("--all-namespaces")
        return self._run_json(cmd)

    def remove_last_applied_configuration(self, namespace, kind, name):
        cmd = [
            "annotate",
            "-n",
            namespace,
            kind,
            name,
            "kubectl.kubernetes.io/last-applied-configuration-",
        ]
        self._run(cmd)

    def _msg_to_process_reconcile_time(self, namespace, resource):
        return OCProcessReconcileTimeDecoratorMsg(
            namespace=namespace,
            resource=resource,
            server=self.server,
            slow_oc_reconcile_threshold=self.slow_oc_reconcile_threshold,
            is_log_slow_oc_reconcile=self.is_log_slow_oc_reconcile,
        )

    def process(self, template, parameters=None):
        if parameters is None:
            parameters = {}
        parameters_to_process = [f"{k}={v}" for k, v in parameters.items()]
        cmd = [
            "process",
            "--local",
            "--ignore-unknown-parameters",
            "-f",
            "-",
        ] + parameters_to_process
        result = self._run(cmd, stdin=json.dumps(template, sort_keys=True))
        return json.loads(result)["items"]

    def release_mirror(self, from_release, to, to_release, dockerconfig):
        with tempfile.NamedTemporaryFile() as fp:
            content = json.dumps(dockerconfig)
            fp.write(content.encode())
            fp.seek(0)

            cmd = [
                "adm",
                "--registry-config",
                fp.name,
                "release",
                "mirror",
                "--from",
                from_release,
                "--to",
                to,
                "--to-release-image",
                to_release,
                "--max-per-registry",
                "1",
            ]

            self._run(cmd)

    @OCDecorators.process_reconcile_time
    def apply(self, namespace, resource):
        cmd = ["apply", "-n", namespace, "-f", "-"]
        self._run(cmd, stdin=resource.toJSON(), apply=True)
        return self._msg_to_process_reconcile_time(namespace, resource.body)

    @OCDecorators.process_reconcile_time
    def create(self, namespace, resource):
        cmd = ["create", "-n", namespace, "-f", "-"]
        self._run(cmd, stdin=resource.toJSON(), apply=True)
        return self._msg_to_process_reconcile_time(namespace, resource.body)

    @OCDecorators.process_reconcile_time
    def replace(self, namespace, resource):
        cmd = ["replace", "-n", namespace, "-f", "-"]
        self._run(cmd, stdin=resource.toJSON(), apply=True)
        return self._msg_to_process_reconcile_time(namespace, resource.body)

    @OCDecorators.process_reconcile_time
    def patch(self, namespace, kind, name, patch):
        cmd = ["patch", "-n", namespace, kind, name, "-p", json.dumps(patch)]
        self._run(cmd)
        resource = {"kind": kind, "metadata": {"name": name}}
        return self._msg_to_process_reconcile_time(namespace, resource)

    @OCDecorators.process_reconcile_time
    def delete(self, namespace, kind, name, cascade=True):
        cmd = [
            "delete",
            "-n",
            namespace,
            kind,
            name,
        ]
        if not cascade:
            cmd.append("--cascade=orphan")
        self._run(cmd)
        resource = {"kind": kind, "metadata": {"name": name}}
        return self._msg_to_process_reconcile_time(namespace, resource)

    @OCDecorators.process_reconcile_time
    def label(self, namespace, kind, name, labels, overwrite=False):
        ns = ["-n", namespace] if namespace else []
        added = [f"{k}={v}" for k, v in labels.items() if v is not None]
        removed = [f"{k}-" for k, v in labels.items() if v is None]
        overwrite_param = f"--overwrite={str(overwrite).lower()}"
        cmd = ["label"] + ns + [kind, name, overwrite_param]
        cmd.extend(added + removed)
        self._run(cmd)
        resource = {"kind": kind, "metadata": {"name": name}}
        return self._msg_to_process_reconcile_time(namespace, resource)

    def project_exists(self, name):
        if self.init_projects:
            return name in self.projects

        try:
            if self.is_kind_supported("Project"):
                self.get(None, "Project.project.openshift.io", name)
            else:
                self.get(None, "Namespace", name)
        except StatusCodeError as e:
            if "NotFound" in str(e):
                return False
            else:
                raise e
        return True

    @OCDecorators.process_reconcile_time
    def new_project(self, namespace):
        if self.is_kind_supported("Project"):
            cmd = ["new-project", namespace]
        else:
            cmd = ["create", "namespace", namespace]
        try:
            self._run(cmd)
        except StatusCodeError as e:
            if "AlreadyExists" not in str(e):
                raise e

        # This return will be removed by the last decorator
        resource = {"kind": "Namespace", "metadata": {"name": namespace}}
        return self._msg_to_process_reconcile_time(namespace, resource)

    @OCDecorators.process_reconcile_time
    def delete_project(self, namespace):
        if self.is_kind_supported("Project"):
            cmd = ["delete", "project", namespace]
        else:
            cmd = ["delete", "namespace", namespace]
        self._run(cmd)

        # This return will be removed by the last decorator
        resource = {"kind": "Namespace", "metadata": {"name": namespace}}
        return self._msg_to_process_reconcile_time(namespace, resource)

    def get_group_if_exists(self, name):
        try:
            return self.get(None, "Group", name)
        except StatusCodeError as e:
            if "NotFound" in str(e):
                return None
            else:
                raise e

    def create_group(self, group):
        if self.get_group_if_exists(group) is not None:
            return
        cmd = ["adm", "groups", "new", group]
        self._run(cmd)

    def delete_group(self, group):
        cmd = ["delete", "group", group]
        self._run(cmd)

    def get_users(self):
        return self.get_all("User")["items"]

    def delete_user(self, user_name):
        user = self.get(None, "User", user_name)
        cmd = ["delete", "user", user_name]
        self._run(cmd)
        for identity in user["identities"]:
            cmd = ["delete", "identity", identity]
            self._run(cmd)

    def add_user_to_group(self, group, user):
        cmd = ["adm", "groups", "add-users", group, user]
        self._run(cmd)

    def del_user_from_group(self, group, user):
        cmd = ["adm", "groups", "remove-users", group, user]
        self._run(cmd)

    def sa_get_token(self, namespace, name):
        cmd = ["sa", "-n", namespace, "get-token", name]
        return self._run(cmd)

    def get_api_resources(self):
        # oc api-resources only has name or wide output
        # and we need to get the KIND, which is the last column
        with self.api_resources_lock:
            if not self.api_resources:
                cmd = ["api-resources", "--no-headers"]
                results = self._run(cmd).decode("utf-8").split("\n")
                self.api_resources = [r.split()[-1] for r in results]
        return self.api_resources

    def get_version(self):
        # this is actually a 10 second timeout, because: oc reasons
        cmd = ["version", "--request-timeout=5"]
        return self._run(cmd)

    @retry(exceptions=(JobNotRunningError), max_attempts=20)
    def wait_for_job_running(self, namespace, name):
        logging.info("waiting for job to run: " + name)
        pods = self.get_items("Pod", namespace=namespace, labels={"job-name": name})

        ready_pods = [
            pod
            for pod in pods
            if pod["status"].get("phase") in ("Running", "Succeeded")
        ]

        if not ready_pods:
            raise JobNotRunningError(name)

    def job_logs(self, namespace, name, follow, output):
        self.wait_for_job_running(namespace, name)
        cmd = ["logs", "-n", namespace, f"job/{name}"]
        if follow:
            cmd.append("-f")
        # pylint: disable=consider-using-with
        output_file = open(os.path.join(output, name), "w")
        # collect logs to file async
        Popen(self.oc_base_cmd + cmd, stdout=output_file)

    @staticmethod
    def get_service_account_username(user):
        namespace = user.split("/")[0]
        name = user.split("/")[1]
        return "system:serviceaccount:{}:{}".format(namespace, name)

    def get_owned_pods(self, namespace, resource):
        pods = self.get(namespace, "Pod")["items"]
        owned_pods = []
        for p in pods:
            owner = self.get_obj_root_owner(namespace, p, allow_not_found=True)
            if (resource.kind, resource.name) == (
                owner["kind"],
                owner["metadata"]["name"],
            ):
                owned_pods.append(p)

        return owned_pods

    def get_owned_replicasets(self, namespace, resource: dict) -> list[dict]:
        owned_replicasets = []
        for rs in self.get(namespace, "ReplicaSet")["items"]:
            owner = self.get_obj_root_owner(namespace, rs, allow_not_found=True)
            if (resource["kind"], resource["metadata"]["name"]) == (
                owner["kind"],
                owner["metadata"]["name"],
            ):
                owned_replicasets.append(rs)

        return owned_replicasets

    @retry(
        exceptions=(ResourceNotFoundError),
        max_attempts=GET_REPLICASET_MAX_ATTEMPTS,
    )
    def get_replicaset(
        self, namespace: str, deployment_resource: dict, allow_empty=False
    ) -> dict:
        """Get last active ReplicaSet for given Deployment.

        Implements similar logic like in kubectl describe deployment.
        """
        for rs in sorted(
            self.get_owned_replicasets(namespace, deployment_resource),
            key=lambda x: x["metadata"]["creationTimestamp"],
            reverse=True,
        ):
            if equal_spec_template(
                rs["spec"]["template"], deployment_resource["spec"]["template"]
            ):
                return rs

        if allow_empty:
            return {}
        raise ResourceNotFoundError("No ReplicaSet found")

    @staticmethod
    def get_pod_owned_pvc_names(pods: Iterable[dict[str, dict]]) -> set[str]:
        owned_pvc_names = set()
        for p in pods:
            vols = p["spec"].get("volumes")
            if not vols:
                continue
            for v in vols:
                with suppress(KeyError):
                    cn = v["persistentVolumeClaim"]["claimName"]
                    owned_pvc_names.add(cn)

        return owned_pvc_names

    @staticmethod
    def get_storage(resource):
        # resources with volumeClaimTemplates
        with suppress(KeyError, IndexError):
            vct = resource["spec"]["volumeClaimTemplates"][0]
            return vct["spec"]["resources"]["requests"]["storage"]

    def resize_pvcs(self, namespace, pvc_names, size):
        patch = {"spec": {"resources": {"requests": {"storage": size}}}}
        for p in pvc_names:
            self.patch(namespace, "PersistentVolumeClaim", p, patch)

    def recycle_orphan_pods(self, namespace, pods):
        for p in pods:
            name = p["metadata"]["name"]
            self.delete(namespace, "Pod", name)
            self.validate_pod_ready(namespace, name)

    @retry(max_attempts=20)
    def validate_pod_ready(self, namespace, name):
        logging.info(
            [self.validate_pod_ready.__name__, self.cluster_name, namespace, name]
        )
        pod = self.get(namespace, "Pod", name)
        for status in pod["status"]["containerStatuses"]:
            if not status["ready"]:
                raise PodNotReadyError(name)

    def recycle_pods(self, dry_run, namespace, dep_kind, dep_resource):
        """recycles pods which are using the specified resources.
        will only act on Secrets containing the 'qontract.recycle' annotation.
        dry_run: simulate pods recycle.
        namespace: namespace in which dependant resource is applied.
        dep_kind: dependant resource kind. currently only supports Secret.
        dep_resource: dependant resource."""

        supported_kinds = ["Secret", "ConfigMap"]
        if dep_kind not in supported_kinds:
            logging.debug(
                [
                    "skipping_pod_recycle_unsupported",
                    self.cluster_name,
                    namespace,
                    dep_kind,
                ]
            )
            return

        dep_annotations = dep_resource.body["metadata"].get("annotations", {})
        qontract_recycle = dep_annotations.get("qontract.recycle")
        if qontract_recycle is True:
            raise RecyclePodsInvalidAnnotationValue('should be "true"')
        if qontract_recycle != "true":
            logging.debug(
                [
                    "skipping_pod_recycle_no_annotation",
                    self.cluster_name,
                    namespace,
                    dep_kind,
                ]
            )
            return

        dep_name = dep_resource.name
        pods = self.get(namespace, "Pod")["items"]

        if dep_kind == "Secret":
            pods_to_recycle = [
                pod for pod in pods if self.secret_used_in_pod(dep_name, pod)
            ]
        elif dep_kind == "ConfigMap":
            pods_to_recycle = [
                pod for pod in pods if self.configmap_used_in_pod(dep_name, pod)
            ]
        else:
            raise RecyclePodsUnsupportedKindError(dep_kind)

        recyclables = {}
        supported_recyclables = [
            "Deployment",
            "DeploymentConfig",
            "StatefulSet",
            "DaemonSet",
        ]
        for pod in pods_to_recycle:
            owner = self.get_obj_root_owner(namespace, pod, allow_not_found=True)
            kind = owner["kind"]
            if kind not in supported_recyclables:
                continue
            recyclables.setdefault(kind, [])
            exists = False
            for obj in recyclables[kind]:
                owner_name = owner["metadata"]["name"]
                if obj["metadata"]["name"] == owner_name:
                    exists = True
                    break
            if not exists:
                recyclables[kind].append(owner)

        for kind, objs in recyclables.items():
            for obj in objs:
                self.recycle(dry_run, namespace, kind, obj)

    @retry(exceptions=ObjectHasBeenModifiedError)
    def recycle(self, dry_run, namespace, kind, obj):
        """Recycles an object by adding a recycle.time annotation

        :param dry_run: Is this a dry run
        :param namespace: Namespace to work in
        :param kind: Object kind
        :param obj: Object to recycle
        """
        name = obj["metadata"]["name"]
        logging.info([f"recycle_{kind.lower()}", self.cluster_name, namespace, name])
        if not dry_run:
            now = datetime.now()
            recycle_time = now.strftime("%d/%m/%Y %H:%M:%S")

            # get the object in case it was modified
            obj = self.get(namespace, kind, name)
            # honor update strategy by setting annotations to force
            # a new rollout
            a = obj["spec"]["template"]["metadata"].get("annotations", {})
            a["recycle.time"] = recycle_time
            obj["spec"]["template"]["metadata"]["annotations"] = a
            cmd = ["apply", "-n", namespace, "-f", "-"]
            stdin = json.dumps(obj, sort_keys=True)
            self._run(cmd, stdin=stdin, apply=True)

    def get_obj_root_owner(
        self, ns, obj, allow_not_found=False, allow_not_controller=False
    ):
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
            allow_not_controller (bool, optional): allow non-controller owner

        Returns:
            dict: representation of the object's owner
        """
        refs = obj["metadata"].get("ownerReferences", [])
        for r in refs:
            if r.get("controller") or allow_not_controller:
                controller_obj = self.get(
                    ns, r["kind"], r["name"], allow_not_found=allow_not_found
                )
                if controller_obj:
                    return self.get_obj_root_owner(
                        ns,
                        controller_obj,
                        allow_not_found=allow_not_found,
                        allow_not_controller=allow_not_controller,
                    )
        return obj

    def secret_used_in_pod(self, name, pod):
        used_resources = self.get_resources_used_in_pod_spec(pod["spec"], "Secret")
        return name in used_resources

    def configmap_used_in_pod(self, name, pod):
        used_resources = self.get_resources_used_in_pod_spec(pod["spec"], "ConfigMap")
        return name in used_resources

    @staticmethod
    def get_resources_used_in_pod_spec(
        spec: dict[str, Any],
        kind: str,
        include_optional: bool = True,
    ) -> dict[str, set[str]]:
        if kind not in ("Secret", "ConfigMap"):
            raise KeyError(f"unsupported resource kind: {kind}")
        optional = "optional"
        if kind == "Secret":
            volume_kind, volume_kind_ref, env_from_kind, env_kind, env_ref = (
                "secret",
                "secretName",
                "secretRef",
                "secretKeyRef",
                "name",
            )
        elif kind == "ConfigMap":
            volume_kind, volume_kind_ref, env_from_kind, env_kind, env_ref = (
                "configMap",
                "name",
                "configMapRef",
                "configMapKeyRef",
                "name",
            )

        resources: dict[str, set[str]] = {}
        for v in spec.get("volumes") or []:
            try:
                volume_ref = v[volume_kind]
                if volume_ref.get(optional) and not include_optional:
                    continue
                resource_name = volume_ref[volume_kind_ref]
                resources.setdefault(resource_name, set())
            except (KeyError, TypeError):
                continue
        for c in spec["containers"] + (spec.get("initContainers") or []):
            for e in c.get("envFrom") or []:
                try:
                    resource_ref = e[env_from_kind]
                    if resource_ref.get(optional) and not include_optional:
                        continue
                    resource_name = resource_ref[env_ref]
                    resources.setdefault(resource_name, set())
                except (KeyError, TypeError):
                    continue
            for e in c.get("env") or []:
                try:
                    resource_ref = e["valueFrom"][env_kind]
                    if resource_ref.get(optional) and not include_optional:
                        continue
                    resource_name = resource_ref[env_ref]
                    resources.setdefault(resource_name, set())
                    secret_key = resource_ref["key"]
                    resources[resource_name].add(secret_key)
                except (KeyError, TypeError):
                    continue

        return resources

    @retry(exceptions=(StatusCodeError, NoOutputError), max_attempts=10)
    def _run(self, cmd, **kwargs):
        if kwargs.get("stdin"):
            stdin = PIPE
            stdin_text = kwargs.get("stdin").encode()
        else:
            stdin = None
            stdin_text = None

        p = Popen(  # pylint: disable=consider-using-with
            self.oc_base_cmd + cmd, stdin=stdin, stdout=PIPE, stderr=PIPE
        )
        out, err = p.communicate(stdin_text)

        code = p.returncode

        allow_not_found = kwargs.get("allow_not_found")

        if code != 0:
            err = err.decode("utf-8")
            if "Unable to connect to the server" in err:
                raise StatusCodeError(f"[{self.server}]: {err}")
            if kwargs.get("apply"):
                if "Invalid value: 0x0" in err:
                    raise InvalidValueApplyError(f"[{self.server}]: {err}")
                if "Invalid value: " in err:
                    if ": field is immutable" in err:
                        if "The Deployment" in err:
                            raise DeploymentFieldIsImmutableError(
                                f"[{self.server}]: {err}"
                            )
                        else:
                            raise FieldIsImmutableError(f"[{self.server}]: {err}")
                    if ": may not change once set" in err:
                        raise MayNotChangeOnceSetError(f"[{self.server}]: {err}")
                    if ": primary clusterIP can not be unset" in err:
                        raise PrimaryClusterIPCanNotBeUnsetError(
                            f"[{self.server}]: {err}"
                        )
                    raise StatusCodeError(f"[{self.server}]: {err}")
                if "metadata.annotations: Too long" in err:
                    raise MetaDataAnnotationsTooLongApplyError(
                        f"[{self.server}]: {err}"
                    )
                if "UnsupportedMediaType" in err:
                    raise UnsupportedMediaTypeError(f"[{self.server}]: {err}")
                if "updates to statefulset spec for fields other than" in err:
                    raise StatefulSetUpdateForbidden(f"[{self.server}]: {err}")
                if "the object has been modified" in err:
                    raise ObjectHasBeenModifiedError(f"[{self.server}]: {err}")
            if not (allow_not_found and "NotFound" in err):
                raise StatusCodeError(f"[{self.server}]: {err}")

        if not out:
            if allow_not_found:
                return "{}"
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

    def is_kind_supported(self, kind: str) -> bool:
        if "." in kind:
            # self.api_resources contains only the short kind names
            kind = kind.split(".", 1)[0]
        return kind in self.get_api_resources()


class OCNative(OCDeprecated):
    def __init__(
        self,
        cluster_name: Optional[str],
        server: Optional[str],
        token: Optional[str],
        jh: Optional[Mapping[Any, Any]] = None,
        settings: Optional[Mapping[Any, Any]] = None,
        init_projects: bool = False,
        local: bool = False,
        insecure_skip_tls_verify: bool = False,
        connection_parameters: Optional[OCConnectionParameters] = None,
    ):
        super().__init__(
            cluster_name,
            server,
            token,
            jh,
            settings,
            init_projects=False,
            init_api_resources=False,
            local=local,
            insecure_skip_tls_verify=insecure_skip_tls_verify,
            connection_parameters=connection_parameters,
        )

        if connection_parameters:
            token = connection_parameters.automation_token
            if connection_parameters.is_cluster_admin:
                token = connection_parameters.cluster_admin_automation_token

            server = connection_parameters.server_url

        if server:
            self.client = self._get_client(server, token)
            self.api_kind_version = self.get_api_resources()
            self.api_resources = self.api_kind_version.keys()
        else:
            raise Exception("A method relies on client/api_kind_version to be set")

        self.object_clients: dict[Any, Any] = {}

        self.init_projects = init_projects
        if self.init_projects:
            if self.is_kind_supported("Project"):
                kind = "Project.project.openshift.io"
            else:
                kind = "Namespace"
            self.projects = [p["metadata"]["name"] for p in self.get_all(kind)["items"]]

    @retry(exceptions=(ServerTimeoutError, InternalServerError, ForbiddenError))
    def _get_client(self, server, token):
        opts = dict(
            api_key={"authorization": f"Bearer {token}"},
            host=server,
            verify_ssl=False,
            # default timeout seems to be 1+ minutes
            retries=5,
        )
        if self.jump_host:
            # the ports could be parameterized, but at this point
            # we only have need of 1 tunnel for 1 service
            self.jump_host.create_ssh_tunnel()
            local_port = self.jump_host.local_port
            opts["proxy"] = f"http://localhost:{local_port}"
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
            return DynamicClient(k8s_client, discoverer=OpenshiftLazyDiscoverer)
        except urllib3.exceptions.MaxRetryError as e:
            raise StatusCodeError(f"[{self.server}]: {e}")

    def _get_obj_client(self, kind, group_version):
        key = f"{kind}.{group_version}"
        if key not in self.object_clients:
            self.object_clients[key] = self.client.resources.get(
                api_version=group_version, kind=kind
            )
        return self.object_clients[key]

    def _parse_kind(self, kind_name):
        kind_group = kind_name.split(".", 1)
        kind = kind_group[0]
        if kind in self.api_kind_version:
            group_version = self.api_kind_version[kind][0]
        else:
            raise StatusCodeError(f"{self.server}: {kind} does not exist")

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
                raise StatusCodeError(
                    f"{self.server}: {apigroup_override}" f" does not have kind {kind}"
                )
        return (kind, group_version)

    # this function returns a kind:apigroup/version map for each kind on the
    # cluster
    def get_api_resources(self):
        c_res = self.client.resources
        # this returns a prefix:apis map
        api_prefix = c_res.parse_api_groups(request_resources=False, update=True)
        kind_groupversion = {}
        for prefix, apis in api_prefix.items():
            # each api prefix consists of api:versions map
            for apigroup, versions in apis.items():
                if prefix == "apis" and len(apigroup) == 0:
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
                            prefix, apigroup, version, True
                        )
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
                                kind, kind_groupversion, r.group_version, obj.preferred
                            )
        return kind_groupversion

    @retry(max_attempts=5, exceptions=(ServerTimeoutError))
    def get_items(self, kind, **kwargs):
        k, group_version = self._parse_kind(kind)
        obj_client = self._get_obj_client(group_version=group_version, kind=k)

        namespace = ""
        if "namespace" in kwargs:
            namespace = kwargs["namespace"]
            # for cluster scoped integrations
            # currently only openshift-clusterrolebindings
            if namespace != "cluster":
                if not self.project_exists(namespace):
                    return []

        labels = ""
        if "labels" in kwargs:
            labels_list = [
                "{}={}".format(k, v) for k, v in kwargs.get("labels").items()
            ]

            labels = ",".join(labels_list)

        resource_names = kwargs.get("resource_names")
        if resource_names:
            items = []
            for resource_name in resource_names:
                try:
                    item = obj_client.get(
                        name=resource_name, namespace=namespace, label_selector=labels
                    )
                    if item:
                        items.append(item.to_dict())
                except NotFoundError:
                    pass
            items_list = {"items": items}
        else:
            items_list = obj_client.get(
                namespace=namespace, label_selector=labels
            ).to_dict()

        items = items_list.get("items")
        if items is None:
            raise Exception("Expecting items")

        return items

    @retry(max_attempts=5, exceptions=(ServerTimeoutError, ForbiddenError))
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
        obj_client = self._get_obj_client(group_version=group_version, kind=k)
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
            group = new.split("/", 1)[0]
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

    def is_kind_supported(self, kind: str) -> bool:
        if "." in kind:
            try:
                self._parse_kind(kind)
                return True
            except StatusCodeError:
                return False
        else:
            return kind in (self.api_resources or {})


OCClient = Union[OCNative, OCDeprecated]


class OCLocal(OCDeprecated):
    def __init__(
        self,
        cluster_name,
        server,
        token,
        local=False,
    ):
        super().__init__(
            cluster_name=cluster_name,
            server=server,
            token=token,
            local=local,
        )


class OC:
    client_status = Counter(
        name="qontract_reconcile_native_client",
        documentation="Cluster is using openshift " "native client",
        labelnames=["cluster_name", "native_client"],
    )

    def __new__(
        cls,
        cluster_name: Optional[str] = None,
        server: Optional[str] = None,
        token: Optional[str] = None,
        jh: Optional[Mapping[Any, Any]] = None,
        settings: Optional[Mapping[Any, Any]] = None,
        init_projects: bool = False,
        init_api_resources: bool = False,
        local: bool = False,
        insecure_skip_tls_verify: bool = False,
        connection_parameters: Optional[OCConnectionParameters] = None,
    ):
        use_native_env = os.environ.get("USE_NATIVE_CLIENT", "")
        use_native = True
        if len(use_native_env) > 0:
            use_native = use_native_env.lower() in ["true", "yes"]
        else:
            enable_toggle = "openshift-resources-native-client"
            use_native = get_feature_toggle_state(
                enable_toggle, context={"cluster_name": cluster_name}
            )

        if connection_parameters:
            cluster_name = connection_parameters.cluster_name

        if use_native:
            OC.client_status.labels(cluster_name=cluster_name, native_client=True).inc()
            return OCNative(
                cluster_name=cluster_name,
                server=server,
                token=token,
                jh=jh,
                settings=settings,
                init_projects=init_projects,
                local=local,
                insecure_skip_tls_verify=insecure_skip_tls_verify,
                connection_parameters=connection_parameters,
            )
        else:
            OC.client_status.labels(
                cluster_name=cluster_name, native_client=False
            ).inc()
            return OCDeprecated(
                cluster_name=cluster_name,
                server=server,
                token=token,
                jh=jh,
                settings=settings,
                init_projects=init_projects,
                init_api_resources=init_api_resources,
                local=local,
                insecure_skip_tls_verify=insecure_skip_tls_verify,
                connection_parameters=connection_parameters,
            )


class OC_Map:
    """
    DEPRECATED! Use reconcile.utils.oc_map.OCMap instead.

    OC_Map gets a GraphQL query results list as input
    and initiates a dictionary of OC clients per cluster.

    The input must contain either 'clusters' or 'namespaces', but not both.

    In case a cluster does not have an automation token
    the OC client will be initiated to False.
    """

    def __init__(
        self,
        clusters=None,
        namespaces=None,
        integration="",
        e2e_test="",
        settings=None,
        internal=None,
        use_jump_host=True,
        thread_pool_size=1,
        init_projects=False,
        init_api_resources=False,
        cluster_admin=False,
    ):
        self.oc_map = {}
        self.privileged_oc_map = {}
        self.calling_integration = integration
        self.calling_e2e_test = e2e_test
        self.settings = settings
        self.internal = internal
        self.use_jump_host = use_jump_host
        self.thread_pool_size = thread_pool_size
        self.init_projects = init_projects
        self.init_api_resources = init_api_resources
        self._lock = Lock()
        self.jh_ports = {}

        if clusters and namespaces:
            raise KeyError("expected only one of clusters or namespaces.")
        elif clusters:
            threaded.run(
                self.init_oc_client,
                clusters,
                self.thread_pool_size,
                privileged=cluster_admin,
            )
        elif namespaces:
            clusters = {}
            privileged_clusters = {}
            for ns_info in namespaces:
                # init a namespace with clusterAdmin with both auth tokens
                # OC_Map is used in various places and even when a namespace
                # declares clusterAdmin token usage, many of those places are
                # happy with regular dedicated-admin and will request a cluster
                # with oc_map.get(cluster) without specifying privileged access
                # specifically
                c = ns_info["cluster"]
                clusters[c["name"]] = c
                privileged = ns_info.get("clusterAdmin", False) or cluster_admin
                if privileged:
                    privileged_clusters[c["name"]] = c
            if clusters:
                threaded.run(
                    self.init_oc_client,
                    clusters.values(),
                    self.thread_pool_size,
                    privileged=False,
                )
            if privileged_clusters:
                threaded.run(
                    self.init_oc_client,
                    privileged_clusters.values(),
                    self.thread_pool_size,
                    privileged=True,
                )
        else:
            raise KeyError("expected one of clusters or namespaces.")

    def set_jh_ports(self, jh):
        # This will be replaced with getting the data from app-interface in
        # a future PR.
        jh["remotePort"] = 8888
        key = f"{jh['hostname']}:{jh['remotePort']}"
        with self._lock:
            if key not in self.jh_ports:
                port = JumpHostSSH.get_unique_random_port()
                self.jh_ports[key] = port
            jh["localPort"] = self.jh_ports[key]

    def init_oc_client(self, cluster_info, privileged: bool):
        cluster = cluster_info["name"]
        if not privileged and self.oc_map.get(cluster):
            return None
        if privileged and self.privileged_oc_map.get(cluster):
            return None
        if self.cluster_disabled(cluster_info):
            return None
        if self.internal is not None:
            # integration is executed with `--internal` or `--external`
            # filter out non matching clusters
            if self.internal and not cluster_info["internal"]:
                return
            if not self.internal and cluster_info["internal"]:
                return

        if privileged:
            automation_token = cluster_info.get("clusterAdminAutomationToken")
            token_name = "admin automation token"
        else:
            automation_token = cluster_info.get("automationToken")
            token_name = "automation token"

        if automation_token is None:
            self.set_oc(
                cluster,
                OCLogMsg(
                    log_level=logging.ERROR, message=f"[{cluster}] has no {token_name}"
                ),
                privileged,
            )
        # serverUrl isn't set when a new cluster is initially created.
        elif not cluster_info.get("serverUrl"):
            self.set_oc(
                cluster,
                OCLogMsg(
                    log_level=logging.ERROR, message=f"[{cluster}] has no serverUrl"
                ),
                privileged,
            )
        else:
            server_url = cluster_info["serverUrl"]
            insecure_skip_tls_verify = cluster_info.get("insecureSkipTLSVerify")
            secret_reader = SecretReader(settings=self.settings)

            try:
                token = secret_reader.read(automation_token)
            except SecretNotFound:
                self.set_oc(
                    cluster,
                    OCLogMsg(
                        log_level=logging.ERROR, message=f"[{cluster}] secret not found"
                    ),
                    privileged,
                )
                return

            if self.use_jump_host:
                jump_host = cluster_info.get("jumpHost")
            else:
                jump_host = None
            if jump_host:
                self.set_jh_ports(jump_host)
            try:
                oc_client = OC(
                    cluster,
                    server_url,
                    token,
                    jump_host,
                    settings=self.settings,
                    init_projects=self.init_projects,
                    init_api_resources=self.init_api_resources,
                    insecure_skip_tls_verify=insecure_skip_tls_verify,
                )
                self.set_oc(cluster, oc_client, privileged)
            except StatusCodeError as e:
                self.set_oc(
                    cluster,
                    OCLogMsg(
                        log_level=logging.ERROR,
                        message=f"[{cluster}]" f" is unreachable: {e}",
                    ),
                    privileged,
                )

    def set_oc(self, cluster: str, value, privileged: bool):
        with self._lock:
            if privileged:
                self.privileged_oc_map[cluster] = value
            else:
                self.oc_map[cluster] = value

    def cluster_disabled(self, cluster_info):
        try:
            integrations = cluster_info["disable"]["integrations"]
            if self.calling_integration.replace("_", "-") in integrations:
                return True
        except (KeyError, TypeError):
            pass
        try:
            tests = cluster_info["disable"]["e2eTests"]
            if self.calling_e2e_test.replace("_", "-") in tests:
                return True
        except (KeyError, TypeError):
            pass

        return False

    def get(self, cluster: str, privileged: bool = False):
        cluster_map = self.privileged_oc_map if privileged else self.oc_map
        return cluster_map.get(
            cluster,
            OCLogMsg(log_level=logging.DEBUG, message=f"[{cluster}] cluster skipped"),
        )

    def get_cluster(self, cluster: str, privileged: bool = False) -> OCClient:
        result = self.get(cluster, privileged)
        if isinstance(result, OCLogMsg):
            raise result
        else:
            return result

    def clusters(
        self, include_errors: bool = False, privileged: bool = False
    ) -> list[str]:
        """
        Get the names of the clusters in the map.
        :param include_errors: includes clusters that had errors, meaning
        that the value in OC_Map might be an OCLogMsg instead of OCNative, etc.
        :return: list of cluster names
        """
        cluster_map = self.privileged_oc_map if privileged else self.oc_map
        if include_errors:
            return list(cluster_map.keys())
        return [k for k, v in cluster_map.items() if v]

    def cleanup(self):
        for oc in self.oc_map.values():
            if oc:
                oc.cleanup()
        for oc in self.privileged_oc_map.values():
            if oc:
                oc.cleanup()


class OCLogMsg(Exception):
    """
    Track log messages associated with initializing OC clients in OC_Map.
    """

    def __init__(self, log_level, message):
        super().__init__()
        self.log_level = log_level
        self.message = message

    def __bool__(self):
        """
        Returning False here makes this object falsy, which is used
        elsewhere when differentiating between an OC client or a log
        message.
        """
        return False


LABEL_MAX_VALUE_LENGTH = 63
LABEL_MAX_KEY_NAME_LENGTH = 63
LABEL_MAX_KEY_PREFIX_LENGTH = 253


def validate_labels(labels: dict[str, str]) -> Iterable[str]:
    """
    Validate a label key/value against some rules from
    https://kubernetes.io/docs/concepts/overview/working-with-objects/labels/#syntax-and-character-set
    Returns a list of erros found, as error message strings
    """
    if labels is None:
        return []

    err = []
    v_pattern = re.compile(r"^(([A-Za-z0-9][-A-Za-z0-9_.]*)?[A-Za-z0-9])?$")
    k_name_pattern = re.compile(r"^([A-Za-z0-9][-A-Za-z0-9_.]*)?[A-Za-z0-9]$")
    k_prefix_pattern = re.compile(
        r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?" r"(\.[a-z0-9]([-a-z0-9]*[a-z0-9])?)*$"
    )

    for k, v in labels.items():
        if len(v) > LABEL_MAX_VALUE_LENGTH:
            err.append(
                f"Label value longer than " f"{LABEL_MAX_VALUE_LENGTH} chars: {v}"
            )
        if not v_pattern.match(v):
            err.append(
                f"Label value is invalid, it needs to match " f"'{v_pattern}': {v}"
            )

        prefix, name = "", k
        if "/" in k:
            split = k.split("/")
            if len(split) > 3:
                err.append(f'Only one "/" allowed in label keys: {k}')
            prefix, name = split[0], split[1]

        if len(name) > LABEL_MAX_KEY_NAME_LENGTH:
            err.append(
                f"Label key name is longer than "
                f"{LABEL_MAX_KEY_NAME_LENGTH} chars: {name}"
            )
        if not k_name_pattern.match(name):
            err.append(
                f"Label key name is invalid, it needs to mach "
                f"'{v_pattern}'': {name}"
            )

        if prefix:
            if len(prefix) > LABEL_MAX_KEY_PREFIX_LENGTH:
                err.append(
                    f"Label key prefix longer than "
                    f"{LABEL_MAX_KEY_PREFIX_LENGTH} chars: {prefix}"
                )
            if not k_prefix_pattern.match(prefix):
                err.append(
                    f"Label key prefix is invalid, it needs to match "
                    f"'{k_prefix_pattern}'': {prefix}"
                )
            if prefix in ("kubernetes.io", "k8s.io"):
                err.append(f"Label key prefix is reserved: {prefix}")

    return err


class OpenshiftLazyDiscoverer(LazyDiscoverer):
    """
    the methods contained in this class have been copied from
    https://github.com/openshift/openshift-restclient-python/blob/master/openshift/dynamic/discovery.py
    """

    def default_groups(self, request_resources=False):
        groups = super().default_groups(request_resources)
        if self.version.get("openshift"):
            groups["oapi"] = {
                "": {
                    "v1": (
                        ResourceGroup(
                            True,
                            resources=self.get_resources_for_api_version(
                                "oapi", "", "v1", True
                            ),
                        )
                        if request_resources
                        else ResourceGroup(True)
                    )
                }
            }
        return groups

    def get(self, **kwargs):
        """Same as search, but will throw an error if there are multiple or no
        results. If there are multiple results and only one is an exact match
        on api_version, that resource will be returned.
        """
        results = self.search(**kwargs)
        # If there are multiple matches, prefer exact matches on api_version
        if len(results) > 1 and kwargs.get("api_version"):
            results = [
                result
                for result in results
                if result.group_version == kwargs["api_version"]
            ]
        # If there are multiple matches, prefer non-List kinds
        if len(results) > 1 and not all(  # pylint: disable=R1729
            [isinstance(x, ResourceList) for x in results]
        ):
            results = [
                result for result in results if not isinstance(result, ResourceList)
            ]
        # if multiple resources are found that share a GVK, prefer the one with the most supported verbs
        if (
            len(results) > 1
            and len(set((x.group_version, x.kind) for x in results)) == 1
        ):
            if len(set(len(x.verbs) for x in results)) != 1:
                results = [max(results, key=lambda x: len(x.verbs))]
        if len(results) == 1:
            return results[0]
        elif not results:
            raise ResourceNotFoundError("No matches found for {}".format(kwargs))
        else:
            raise ResourceNotUniqueError(
                "Multiple matches found for {}: {}".format(kwargs, results)
            )
