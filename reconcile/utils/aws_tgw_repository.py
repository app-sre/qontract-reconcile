from typing import (
    Iterable,
    Optional,
    Union,
    cast,
)

from pydantic.main import BaseModel

from reconcile.gql_definitions.common.clusters_with_peering import (
    ClusterPeeringConnectionAccountTGWV1,
    ClusterPeeringConnectionAccountV1,
    ClusterPeeringConnectionAccountVPCMeshV1,
    ClusterPeeringConnectionClusterRequesterV1,
    ClusterPeeringConnectionV1,
    ClusterV1,
)
from reconcile.gql_definitions.terraform_tgw_attachments.aws_accounts import (
    AWSAccountV1,
)
from reconcile.typed_queries.clusters_with_peering import get_clusters_with_peering
from reconcile.typed_queries.terraform_tgw_attachments.aws_accounts import (
    get_aws_accounts,
)
from reconcile.utils import gql

TGW_CONNECTION_PROVIDER = "account-tgw"


class AWSTGWClustersAndAccounts(BaseModel):
    clusters: list[ClusterV1]
    accounts: list[AWSAccountV1]


class AWSTGWRepository:
    def __init__(self, gql_api: gql.GqlApi) -> None:
        self.gql_api = gql_api

    def get_tgw_clusters_and_accounts(
        self,
        account_name: Optional[str] = None,
    ) -> AWSTGWClustersAndAccounts:
        clusters = get_clusters_with_peering(self.gql_api)
        tgw_clusters = self._filter_tgw_clusters(clusters, account_name)
        accounts = get_aws_accounts(self.gql_api, name=account_name)
        tgw_accounts = self._filter_tgw_accounts(accounts, tgw_clusters)
        return AWSTGWClustersAndAccounts(
            clusters=tgw_clusters,
            accounts=tgw_accounts,
        )

    @staticmethod
    def is_tgw_peer_connection(
        peer_connection: Union[
            ClusterPeeringConnectionAccountTGWV1,
            ClusterPeeringConnectionAccountV1,
            ClusterPeeringConnectionAccountVPCMeshV1,
            ClusterPeeringConnectionClusterRequesterV1,
            ClusterPeeringConnectionV1,
        ],
        account_name: Optional[str],
    ) -> bool:
        if peer_connection.provider != TGW_CONNECTION_PROVIDER:
            return False
        if account_name is None:
            return True
        tgw_peer_connection = cast(
            ClusterPeeringConnectionAccountTGWV1, peer_connection
        )
        return tgw_peer_connection.account.name == account_name

    @staticmethod
    def _is_tgw_cluster(
        cluster: ClusterV1,
        account_name: Optional[str] = None,
    ) -> bool:
        return any(
            AWSTGWRepository.is_tgw_peer_connection(pc, account_name)
            for pc in cluster.peering.connections  # type: ignore[union-attr]
        )

    @staticmethod
    def _filter_tgw_clusters(
        clusters: Iterable[ClusterV1],
        account_name: Optional[str] = None,
    ) -> list[ClusterV1]:
        return [
            c for c in clusters if AWSTGWRepository._is_tgw_cluster(c, account_name)
        ]

    @staticmethod
    def _filter_tgw_accounts(
        accounts: Iterable[AWSAccountV1],
        tgw_clusters: Iterable[ClusterV1],
    ) -> list[AWSAccountV1]:
        tgw_account_names = set()
        for cluster in tgw_clusters:
            for peer_connection in cluster.peering.connections:  # type: ignore[union-attr]
                if peer_connection.provider == TGW_CONNECTION_PROVIDER:
                    tgw_peer_connection = cast(
                        ClusterPeeringConnectionAccountTGWV1, peer_connection
                    )
                    tgw_account_names.add(tgw_peer_connection.account.name)
        return [a for a in accounts if a.name in tgw_account_names]
