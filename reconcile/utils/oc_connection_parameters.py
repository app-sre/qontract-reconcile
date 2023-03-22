from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import (
    Optional,
    Protocol,
)

from sretoolbox.utils import threaded

from reconcile.utils.secret_reader import (
    HasSecret,
    SecretNotFound,
    SecretReaderBase,
)


class Disable(Protocol):
    integrations: Optional[list[str]]
    e2e_tests: Optional[list[str]]


class Jumphost(Protocol):
    hostname: str
    port: Optional[int]
    remote_port: Optional[int]
    known_hosts: str
    user: str

    @property
    def identity(self) -> HasSecret:
        ...


class Cluster(Protocol):
    name: str
    server_url: str
    internal: Optional[bool]
    insecure_skip_tls_verify: Optional[bool]

    @property
    def jump_host(self) -> Optional[Jumphost]:
        ...

    @property
    def automation_token(self) -> Optional[HasSecret]:
        ...

    @property
    def cluster_admin_automation_token(self) -> Optional[HasSecret]:
        ...

    @property
    def disable(self) -> Optional[Disable]:
        ...


class Namespace(Protocol):
    cluster_admin: Optional[bool]

    @property
    def cluster(self) -> Cluster:
        ...


@dataclass
class OCConnectionParameters:
    """
    Container for Openshift Client (OC) parameters.
    These parameters are necessary to initialize a connection to a cluster.
    As a convenience, this class is able to convert generated classes
    into proper OC connection parameters.
    """

    cluster_name: str
    server_url: str
    is_internal: Optional[bool]
    is_cluster_admin: bool
    skip_tls_verify: Optional[bool]
    automation_token: Optional[str]
    cluster_admin_automation_token: Optional[str]
    disabled_integrations: list[str]
    disabled_e2e_tests: list[str]
    jumphost_hostname: Optional[str]
    jumphost_known_hosts: Optional[str]
    jumphost_user: Optional[str]
    jumphost_port: Optional[int]
    jumphost_key: Optional[str]
    jumphost_remote_port: Optional[int]
    # The local port is currently calculated and set outside of this class
    jumphost_local_port: Optional[int]

    @staticmethod
    def from_cluster(
        cluster: Cluster,
        secret_reader: SecretReaderBase,
        cluster_admin: bool,
        use_jump_host: bool = True,
    ) -> OCConnectionParameters:
        automation_token: Optional[str] = None
        cluster_admin_automation_token: Optional[str] = None

        if cluster_admin:
            if cluster.cluster_admin_automation_token:
                try:
                    cluster_admin_automation_token = secret_reader.read_secret(
                        cluster.cluster_admin_automation_token
                    )
                except SecretNotFound:
                    logging.error(
                        f"[{cluster.name}] admin token {cluster.cluster_admin_automation_token} not found"
                    )
            else:
                # Note, that currently OCMap uses OCLogMsg if a token is missing, i.e.,
                # for now this is valid behavior.
                logging.debug(
                    f"No admin automation token set for cluster '{cluster.name}', but privileged access requested."
                )
        else:
            if cluster.automation_token:
                try:
                    automation_token = secret_reader.read_secret(
                        cluster.automation_token
                    )
                except SecretNotFound:
                    logging.error(
                        f"[{cluster.name}] automation token {cluster.automation_token} not found"
                    )
            else:
                # Note, that currently OCMap uses OCLogMsg if a token is missing, i.e.,
                # for now this is valid behavior.
                logging.debug(f"No automation token for cluster '{cluster.name}'.")

        disabled_integrations = []
        disabled_e2e_tests = []
        if cluster.disable:
            disabled_integrations = cluster.disable.integrations or []
            disabled_e2e_tests = cluster.disable.e2e_tests or []

        jumphost_hostname = None
        jumphost_known_hosts = None
        jumphost_user = None
        jumphost_port = None
        jumphost_key = None
        jumphost_remote_port = None
        jumphost_local_port = None
        if use_jump_host and cluster.jump_host:
            jumphost_hostname = cluster.jump_host.hostname
            jumphost_known_hosts = cluster.jump_host.known_hosts
            jumphost_user = cluster.jump_host.user
            jumphost_port = cluster.jump_host.port
            jumphost_remote_port = cluster.jump_host.remote_port

            try:
                jumphost_key = secret_reader.read_secret(cluster.jump_host.identity)
            except SecretNotFound as e:
                logging.error(
                    f"[{cluster.name}] jumphost secret {cluster.jump_host.identity} not found"
                )
                raise e

        return OCConnectionParameters(
            cluster_name=cluster.name,
            server_url=cluster.server_url,
            is_internal=cluster.internal,
            skip_tls_verify=cluster.insecure_skip_tls_verify,
            disabled_e2e_tests=disabled_e2e_tests,
            disabled_integrations=disabled_integrations,
            automation_token=automation_token,
            jumphost_hostname=jumphost_hostname,
            jumphost_key=jumphost_key,
            jumphost_known_hosts=jumphost_known_hosts,
            jumphost_user=jumphost_user,
            jumphost_port=jumphost_port,
            jumphost_remote_port=jumphost_remote_port,
            jumphost_local_port=jumphost_local_port,
            cluster_admin_automation_token=cluster_admin_automation_token,
            is_cluster_admin=cluster_admin,
        )


def _filter_unique_clusters_from_namespace(
    namespaces: Iterable[Namespace],
) -> list[Cluster]:
    unique_by_cluster_name = {ns.cluster.name: ns.cluster for ns in namespaces}
    return list(unique_by_cluster_name.values())


def get_oc_connection_parameters_from_clusters(
    secret_reader: SecretReaderBase,
    clusters: Iterable[Cluster],
    thread_pool_size: int = 1,
    use_jump_host: bool = True,
) -> list[OCConnectionParameters]:
    """
    Convert nested generated cluster classes from queries into flat ClusterParameter objects.
    Also fetch required ClusterParameter secrets from vault with multiple threads.
    ClusterParameter objects are used to initialize an OCMap.
    """
    unique_clusers = list({c.name: c for c in clusters}.values())
    parameters: list[OCConnectionParameters] = threaded.run(
        OCConnectionParameters.from_cluster,
        unique_clusers,
        thread_pool_size,
        secret_reader=secret_reader,
        use_jump_host=use_jump_host,
        cluster_admin=False,
    )
    return parameters


def get_oc_connection_parameters_from_namespaces(
    secret_reader: SecretReaderBase,
    namespaces: Iterable[Namespace],
    thread_pool_size: int = 1,
    use_jump_host: bool = True,
    cluster_admin: bool = False,
) -> list[OCConnectionParameters]:
    """
    Convert nested generated namespace classes from queries into flat ClusterParameter objects.
    Also fetch required ClusterParameter secrets from vault with multiple threads.
    ClusterParameter objects are used to initialize an OCMap.
    """

    # init a namespace with clusterAdmin with both auth tokens
    # OC_Map is used in various places and even when a namespace
    # declares clusterAdmin token usage, many of those places are
    # happy with regular dedicated-admin and will request a cluster
    # with oc_map.get(cluster) without specifying privileged access
    # specifically
    all_unique_clusters = _filter_unique_clusters_from_namespace(namespaces=namespaces)
    unique_privileged_clusters = _filter_unique_clusters_from_namespace(
        namespaces=(ns for ns in namespaces if (ns.cluster_admin or cluster_admin))
    )

    unprivileged_connections: list[OCConnectionParameters] = threaded.run(
        OCConnectionParameters.from_cluster,
        all_unique_clusters,
        thread_pool_size,
        secret_reader=secret_reader,
        use_jump_host=use_jump_host,
        cluster_admin=False,
        return_exceptions=True,
    )

    privileged_connections: list[OCConnectionParameters] = threaded.run(
        OCConnectionParameters.from_cluster,
        unique_privileged_clusters,
        thread_pool_size,
        secret_reader=secret_reader,
        use_jump_host=use_jump_host,
        cluster_admin=True,
        return_exceptions=True,
    )

    return unprivileged_connections + privileged_connections
