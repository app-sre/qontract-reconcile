import logging
from collections.abc import Iterable
from threading import Lock
from typing import (
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
from reconcile.utils.oc_connection_parameters import (
    Cluster,
    Namespace,
    OCConnectionParameters,
    get_oc_connection_parameters_from_clusters,
    get_oc_connection_parameters_from_namespaces,
)
from reconcile.utils.secret_reader import SecretReaderBase


class OCMap:
    """
    OCMap takes a list of OCConnectionParameters as input
    and initializes a dictionary of Openshift Clients (OC) per cluster.

    In case a connection parameter does not have an automation token
    the OC client will be initiated with a OCLogMessage.

    For convenience, use init_oc_map_from_clusters() or
    init_oc_map_from_namespaces() to initiate an OCMap object.
    """

    def __init__(
        self,
        connection_parameters: Iterable[OCConnectionParameters],
        integration: str = "",
        e2e_test: str = "",
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

    def _set_jumphost_tunnel_ports(
        self, connection_parameters: OCConnectionParameters
    ) -> None:
        key = f"{connection_parameters.jumphost_hostname}:{connection_parameters.jumphost_remote_port}"
        with self._lock:
            if key not in self._jh_ports:
                port = JumpHostSSH.get_unique_random_port()
                self._jh_ports[key] = port
            connection_parameters.jumphost_local_port = self._jh_ports[key]

    def _init_oc_client(
        self, connection_parameters: OCConnectionParameters, privileged: bool
    ) -> None:
        cluster = connection_parameters.cluster_name
        if not privileged and self._oc_map.get(cluster):
            return None
        if privileged and self._privileged_oc_map.get(cluster):
            return None
        if self._is_cluster_disabled(connection_parameters):
            return None
        if self._internal is not None:
            # integration is executed with `--internal` or `--external`
            # filter out non matching clusters
            if self._internal and not connection_parameters.is_internal:
                return
            if not self._internal and connection_parameters.is_internal:
                return

        if privileged:
            automation_token = connection_parameters.cluster_admin_automation_token
            token_name = "clusterAdminAutomationToken"
        else:
            automation_token = connection_parameters.automation_token
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
        elif not connection_parameters.server_url:
            self._set_oc(
                cluster,
                OCLogMsg(
                    log_level=logging.ERROR, message=f"[{cluster}] has no serverUrl"
                ),
                privileged,
            )
        else:
            if self._use_jump_host and connection_parameters.jumphost_hostname:
                self._set_jumphost_tunnel_ports(
                    connection_parameters=connection_parameters
                )
            try:
                # TODO: wait for next mypy release to support this
                # https://github.com/python/mypy/issues/14426
                oc_client: Union[OCDeprecated, OCLogMsg] = OC(  # type: ignore
                    connection_parameters=connection_parameters,
                    init_projects=self._init_projects,
                    init_api_resources=self._init_api_resources,
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


def init_oc_map_from_clusters(
    clusters: Iterable[Cluster],
    secret_reader: SecretReaderBase,
    integration: str = "",
    e2e_test: str = "",
    internal: Optional[bool] = None,
    use_jump_host: bool = True,
    thread_pool_size: int = 1,
    init_projects: bool = False,
    init_api_resources: bool = False,
    cluster_admin: bool = False,
) -> OCMap:
    """
    Convenience function to hide connection_parameters implementation
    from caller.
    """
    connection_parameters = get_oc_connection_parameters_from_clusters(
        clusters=clusters,
        secret_reader=secret_reader,
        thread_pool_size=2,
    )
    return OCMap(
        connection_parameters=connection_parameters,
        integration=integration,
        e2e_test=e2e_test,
        internal=internal,
        use_jump_host=use_jump_host,
        thread_pool_size=thread_pool_size,
        init_projects=init_projects,
        init_api_resources=init_api_resources,
        cluster_admin=cluster_admin,
    )


def init_oc_map_from_namespaces(
    namespaces: Iterable[Namespace],
    secret_reader: SecretReaderBase,
    integration: str = "",
    e2e_test: str = "",
    internal: Optional[bool] = None,
    use_jump_host: bool = True,
    thread_pool_size: int = 1,
    init_projects: bool = False,
    init_api_resources: bool = False,
    cluster_admin: bool = False,
) -> OCMap:
    """
    Convenience function to hide connection_parameters implementation
    from caller.
    """
    connection_parameters = get_oc_connection_parameters_from_namespaces(
        namespaces=namespaces,
        secret_reader=secret_reader,
        thread_pool_size=2,
    )
    return OCMap(
        connection_parameters=connection_parameters,
        integration=integration,
        e2e_test=e2e_test,
        internal=internal,
        use_jump_host=use_jump_host,
        thread_pool_size=thread_pool_size,
        init_projects=init_projects,
        init_api_resources=init_api_resources,
        cluster_admin=cluster_admin,
    )
