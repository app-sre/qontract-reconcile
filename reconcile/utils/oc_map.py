import logging
from collections.abc import (
    Iterable,
    Mapping,
    MutableMapping,
)
from threading import Lock
from typing import (
    Any,
    Optional,
    Union,
)

from sretoolbox.utils import threaded

from reconcile.utils.jump_host import JumpHostSSH
from reconcile.utils.oc import (
    OC,
    OCDeprecated,
    OCLogMsg,
    StatusCodeError,
)
from reconcile.utils.oc_connection_parameters import OCConnectionParameters


class OCMap:
    """
    DO NOT USE YET! This class is still in refactoring state.
    Only selected integrations are using this class for now.

    OCMap takes a list of OCConnectionParameters as input
    and initializes a dictionary of Openshift Clients (OC) per cluster.

    In case a connection parameter does not have an automation token
    the OC client will be initiated with a OCLogMessage.
    """

    def __init__(
        self,
        connection_parameters: Iterable[OCConnectionParameters],
        clusters_untyped: Optional[Iterable[MutableMapping[Any, Any]]] = None,
        namespaces_untyped: Optional[Iterable[MutableMapping[Any, Any]]] = None,
        integration: str = "",
        e2e_test: str = "",
        settings_untyped: Optional[Mapping[Any, Any]] = None,
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
        self._internal = internal
        self._use_jump_host = use_jump_host
        self._thread_pool_size = thread_pool_size
        self._init_projects = init_projects
        self._init_api_resources = init_api_resources
        self._lock = Lock()
        self._jh_ports: dict[str, int] = {}
        self._settings_dict = settings_untyped

        # TODO: remove these once jumphosts are typed
        # ############################################
        self._jumphosts_dict: dict[Any, Any] = {}
        for cluster_dict in clusters_untyped or []:
            self._jumphosts_dict[cluster_dict.get("name")] = cluster_dict.get(
                "jumpHost"
            )
        for ns_dict in namespaces_untyped or []:
            cluster_d = ns_dict.get("cluster")
            if cluster_d:
                self._jumphosts_dict[cluster_d.get("name")] = cluster_d.get("jumpHost")
        # ############################################

        # init a namespace with clusterAdmin with both auth tokens
        # OC_Map is used in various places and even when a namespace
        # declares clusterAdmin token usage, many of those places are
        # happy with regular dedicated-admin and will request a cluster
        # with oc_map.get(cluster) without specifying privileged access
        # specifically
        privileged_clusters: list[OCConnectionParameters] = [
            c for c in connection_parameters if (c.is_cluster_admin or cluster_admin)
        ]
        unprivileged_clusters: list[OCConnectionParameters] = [
            c
            for c in connection_parameters
            if not (c.is_cluster_admin or cluster_admin)
        ]

        threaded.run(
            self._init_oc_client,
            unprivileged_clusters,
            self._thread_pool_size,
            privileged=False,
        )
        threaded.run(
            self._init_oc_client,
            privileged_clusters,
            self._thread_pool_size,
            privileged=True,
        )

    def _set_jh_ports(self, jh: MutableMapping[Any, Any]) -> None:
        # This will be replaced with getting the data from app-interface in
        # a future PR.
        jh["remotePort"] = 8888
        key = f"{jh['hostname']}:{jh['remotePort']}"
        with self._lock:
            if key not in self._jh_ports:
                port = JumpHostSSH.get_unique_random_port()
                self._jh_ports[key] = port
            jh["localPort"] = self._jh_ports[key]

    def _init_oc_client(
        self, cluster_info: OCConnectionParameters, privileged: bool
    ) -> None:
        cluster = cluster_info.cluster_name
        if not privileged and self._oc_map.get(cluster):
            return None
        if privileged and self._privileged_oc_map.get(cluster):
            return None
        if self._is_cluster_disabled(cluster_info):
            return None
        if self._internal is not None:
            # integration is executed with `--internal` or `--external`
            # filter out non matching clusters
            if self._internal and not cluster_info.is_internal:
                return
            if not self._internal and cluster_info.is_internal:
                return

        if privileged:
            automation_token = cluster_info.cluster_admin_automation_token
            token_name = "clusterAdminAutomationToken"
        else:
            automation_token = cluster_info.automation_token
            token_name = "automationToken"

        if automation_token is None:
            self._set_oc(
                cluster,
                OCLogMsg(
                    log_level=logging.ERROR, message=f"[{cluster}] has no {token_name}"
                ),
                privileged,
            )
        # serverUrl isn't set when a new cluster is initially created.
        elif not cluster_info.server_url:
            self._set_oc(
                cluster,
                OCLogMsg(
                    log_level=logging.ERROR, message=f"[{cluster}] has no serverUrl"
                ),
                privileged,
            )
        else:
            server_url = cluster_info.server_url
            insecure_skip_tls_verify = cluster_info.skip_tls_verify

            if self._use_jump_host:
                jump_host = self._jumphosts_dict[cluster_info.cluster_name]
            else:
                jump_host = None
            if jump_host:
                self._set_jh_ports(jump_host)
            try:
                # TODO: wait for next mypy release to support this
                # https://github.com/python/mypy/issues/14426
                oc_client: Union[OCDeprecated, OCLogMsg] = OC(  # type: ignore
                    cluster,
                    server_url,
                    automation_token,
                    jump_host,
                    settings=self._settings_dict,
                    init_projects=self._init_projects,
                    init_api_resources=self._init_api_resources,
                    insecure_skip_tls_verify=insecure_skip_tls_verify,
                )
                self._set_oc(cluster, oc_client, privileged)
            except StatusCodeError as e:
                self._set_oc(
                    cluster,
                    OCLogMsg(
                        log_level=logging.ERROR,
                        message=f"[{cluster}]" f" is unreachable: {e}",
                    ),
                    privileged,
                )

    def _set_oc(
        self, cluster: str, value: Union[OCDeprecated, OCLogMsg], privileged: bool
    ) -> None:
        with self._lock:
            if privileged:
                self._privileged_oc_map[cluster] = value
            else:
                self._oc_map[cluster] = value

    def _is_cluster_disabled(self, cluster_info: OCConnectionParameters) -> bool:
        try:
            integrations = cluster_info.disabled_integrations or []
            if self._calling_integration.replace("_", "-") in integrations:
                return True
        except (KeyError, TypeError):
            pass

        try:
            tests = cluster_info.disabled_e2e_tests or []
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
