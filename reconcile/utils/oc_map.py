import logging
from threading import Lock
from typing import (
    Any,
    Mapping,
    MutableMapping,
    Optional,
    Protocol,
    Sequence,
    Union,
)

from sretoolbox.utils import threaded

from reconcile.utils.oc import (
    OC,
    JumpHostSSH,
    OCDeprecated,
    OCLogMsg,
    StatusCodeError,
)
from reconcile.utils.secret_reader import (
    HasSecret,
    SecretNotFound,
    SecretReaderBase,
)


class HasDisable(Protocol):
    integrations: Optional[list[str]]
    e2e_tests: Optional[list[str]]


class HasCluster(Protocol):
    name: str
    server_url: str
    internal: Optional[bool]
    insecure_skip_tls_verify: Optional[bool]

    @property
    def automation_token(self) -> Optional[HasSecret]:
        ...

    @property
    def cluster_admin_automation_token(self) -> Optional[HasSecret]:
        ...

    @property
    def disable(self) -> Optional[HasDisable]:
        ...


class HasNamespace(Protocol):
    cluster: HasCluster
    cluster_admin: Optional[bool]


class OCMap:
    """OCMap gets a GraphQL query results list as input
    and initiates a dictionary of OC clients per cluster.

    The input must contain either 'clusters' or 'namespaces', but not both.

    In case a cluster does not have an automation token
    the OC client will be initiated with a OCLogMessage.
    """

    def __init__(
        self,
        clusters: Optional[Sequence[HasCluster]] = None,
        clusters_untyped: Optional[Sequence[MutableMapping[Any, Any]]] = None,
        namespaces: Optional[Sequence[HasNamespace]] = None,
        namespaces_untyped: Optional[Sequence[MutableMapping[Any, Any]]] = None,
        integration: str = "",
        e2e_test: str = "",
        settings_untyped: Optional[Mapping[Any, Any]] = None,
        secret_reader: Optional[SecretReaderBase] = None,
        internal: Optional[bool] = None,
        use_jump_host: bool = True,
        thread_pool_size: int = 1,
        init_projects: bool = False,
        init_api_resources: bool = False,
        cluster_admin: bool = False,
    ):
        self._oc_map: dict[str, Union[OCDeprecated, OCLogMsg]] = {}
        self._privileged_oc_map: dict[str, Union[OCDeprecated, OCLogMsg]] = {}
        self._calling_integration = integration
        self._calling_e2e_test = e2e_test
        self._secret_reader = secret_reader
        self._internal = internal
        self._use_jump_host = use_jump_host
        self._thread_pool_size = thread_pool_size
        self._init_projects = init_projects
        self._init_api_resources = init_api_resources
        self._lock = Lock()
        self._jh_ports: dict[str, int] = {}
        self._settings_dict = settings_untyped
        self._jumphosts_dict: dict[Any, Any] = {}

        if clusters and namespaces:
            raise KeyError("expected only one of clusters or namespaces.")
        elif clusters and clusters_untyped:
            for cluster_dict in clusters_untyped:
                self._jumphosts_dict[cluster_dict.get("name")] = cluster_dict.get(
                    "jumpHost"
                )
            threaded.run(
                self.init_oc_client,
                clusters,
                self._thread_pool_size,
                privileged=cluster_admin,
            )
        elif namespaces and namespaces_untyped:
            for ns_dict in namespaces_untyped:
                cluster_d = ns_dict.get("cluster")
                if cluster_d:
                    self._jumphosts_dict[cluster_d.get("name")] = cluster_d.get(
                        "jumpHost"
                    )
            clusters_dict: dict[str, HasCluster] = {}
            privileged_clusters: dict[str, HasCluster] = {}
            for ns_info in namespaces:
                # init a namespace with clusterAdmin with both auth tokens
                # OC_Map is used in various places and even when a namespace
                # declares clusterAdmin token usage, many of those places are
                # happy with regular dedicated-admin and will request a cluster
                # with oc_map.get(cluster) without specifying privileged access
                # specifically
                c = ns_info.cluster
                clusters_dict[c.name] = c
                privileged = ns_info.cluster_admin or cluster_admin
                if privileged:
                    privileged_clusters[c.name] = c
            if clusters_dict:
                threaded.run(
                    self.init_oc_client,
                    clusters_dict.values(),
                    self._thread_pool_size,
                    privileged=False,
                )
            if privileged_clusters:
                threaded.run(
                    self.init_oc_client,
                    privileged_clusters.values(),
                    self._thread_pool_size,
                    privileged=True,
                )
        else:
            raise KeyError("expected one of clusters or namespaces.")

    def set_jh_ports(self, jh: MutableMapping[Any, Any]) -> None:
        # This will be replaced with getting the data from app-interface in
        # a future PR.
        jh["remotePort"] = 8888
        key = f"{jh['hostname']}:{jh['remotePort']}"
        with self._lock:
            if key not in self._jh_ports:
                port = JumpHostSSH.get_unique_random_port()
                self._jh_ports[key] = port
            jh["localPort"] = self._jh_ports[key]

    def init_oc_client(self, cluster_info: HasCluster, privileged: bool) -> None:
        cluster = cluster_info.name
        if not privileged and self._oc_map.get(cluster):
            return None
        if privileged and self._privileged_oc_map.get(cluster):
            return None
        if self.cluster_disabled(cluster_info):
            return None
        if self._internal is not None:
            # integration is executed with `--internal` or `--external`
            # filter out non matching clusters
            if self._internal and not cluster_info.internal:
                return
            if not self._internal and cluster_info.internal:
                return

        if privileged:
            automation_token = cluster_info.cluster_admin_automation_token
            token_name = "clusterAdminAutomationToken"
        else:
            automation_token = cluster_info.automation_token
            token_name = "automationToken"

        if automation_token is None:
            self.set_oc(
                cluster,
                OCLogMsg(
                    log_level=logging.ERROR, message=f"[{cluster}] has no {token_name}"
                ),
                privileged,
            )
        # serverUrl isn't set when a new cluster is initially created.
        elif not cluster_info.server_url:
            self.set_oc(
                cluster,
                OCLogMsg(
                    log_level=logging.ERROR, message=f"[{cluster}] has no serverUrl"
                ),
                privileged,
            )
        else:
            server_url = cluster_info.server_url
            insecure_skip_tls_verify = cluster_info.insecure_skip_tls_verify

            try:
                if not self._secret_reader:
                    raise Exception("No secret_reader set")
                token = self._secret_reader.read_secret(automation_token)
            except SecretNotFound:
                self.set_oc(
                    cluster,
                    OCLogMsg(
                        log_level=logging.ERROR, message=f"[{cluster}] secret not found"
                    ),
                    privileged,
                )
                return

            if self._use_jump_host:
                jump_host = self._jumphosts_dict[cluster_info.name]
            else:
                jump_host = None
            if jump_host:
                self.set_jh_ports(jump_host)
            try:
                # TODO: wait for next mypy release to support this
                # https://github.com/python/mypy/issues/14426
                oc_client: Union[OCDeprecated, OCLogMsg] = OC(  # type: ignore
                    cluster,
                    server_url,
                    token,
                    jump_host,
                    settings=self._settings_dict,
                    init_projects=self._init_projects,
                    init_api_resources=self._init_api_resources,
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

    def set_oc(
        self, cluster: str, value: Union[OCDeprecated, OCLogMsg], privileged: bool
    ) -> None:
        with self._lock:
            if privileged:
                self._privileged_oc_map[cluster] = value
            else:
                self._oc_map[cluster] = value

    def cluster_disabled(self, cluster_info: HasCluster) -> bool:
        try:
            integrations = []
            if cluster_info.disable:
                integrations = cluster_info.disable.integrations or []
            if self._calling_integration.replace("_", "-") in integrations:
                return True
        except (KeyError, TypeError):
            pass

        try:
            tests = []
            if cluster_info.disable:
                tests = cluster_info.disable.e2e_tests or []
            if self._calling_e2e_test.replace("_", "-") in tests:
                return True
        except (KeyError, TypeError):
            pass
        return False

    def get(
        self, cluster: str, privileged: bool = False
    ) -> Optional[Union[OCDeprecated, OCLogMsg]]:
        cluster_map = self._privileged_oc_map if privileged else self._oc_map
        return cluster_map.get(
            cluster,
            OCLogMsg(log_level=logging.DEBUG, message=f"[{cluster}] cluster skipped"),
        )

    def get_cluster(
        self, cluster: str, privileged: bool = False
    ) -> Optional[Union[OCDeprecated, OCLogMsg]]:
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
        cluster_map = self._privileged_oc_map if privileged else self._oc_map
        if include_errors:
            return list(cluster_map.keys())
        return [k for k, v in cluster_map.items() if v]

    def cleanup(self) -> None:
        for oc in self._oc_map.values():
            if oc and isinstance(oc, OCDeprecated):
                oc.cleanup()
        for oc in self._privileged_oc_map.values():
            if oc and isinstance(oc, OCDeprecated):
                oc.cleanup()
