import random
from collections.abc import (
    Callable,
    Sequence,
)
from textwrap import dedent
from typing import Any

import pytest
from pytest_mock import MockerFixture

from reconcile.aws_version_sync.integration import (
    AVSIntegration,
    AVSIntegrationParams,
    ExternalResource,
    ExternalResourceProvisioner,
)
from reconcile.aws_version_sync.merge_request_manager.merge_request_manager import (
    MergeRequestManager,
    MrData,
)
from reconcile.aws_version_sync.utils import prom_get
from reconcile.gql_definitions.aws_version_sync.clusters import (
    ClusterV1 as AWSResourceExporterClusterV1,
)
from reconcile.gql_definitions.aws_version_sync.namespaces import NamespaceV1
from reconcile.test.fixtures import Fixtures
from reconcile.utils.gql import GqlApi
from reconcile.utils.secret_reader import SecretReader


@pytest.fixture
def intg(secret_reader: SecretReader, mocker: MockerFixture) -> AVSIntegration:
    mocker.patch.object(AVSIntegration, "secret_reader", secret_reader)
    return AVSIntegration(
        AVSIntegrationParams(
            aws_resource_exporter_clusters=[
                "aws-resource-exporter-cluster-1",
                # this cluster should not be included because
                # the integration disable on it
                "aws-resource-exporter-cluster-2",
            ],
            supported_providers=["rds", "elasticache"],
            # all clusters in namespaces.yml except cluster-5
            clusters=["cluster-1", "cluster-2", "cluster-3", "cluster-4"],
            prometheus_timeout=0,
        )
    )


@pytest.fixture
def namespaces(
    data_factory: Callable, fx: Fixtures, intg: AVSIntegration
) -> list[NamespaceV1]:
    def q(*args: Any, **kwargs: Any) -> dict:
        return {
            "namespaces": [
                data_factory(NamespaceV1, ns)
                for ns in fx.get_anymarkup("namespaces.yml")
            ]
        }

    return intg.get_namespaces(q, clusters=intg.params.clusters)


@pytest.fixture
def clusters(fx: Fixtures, intg: AVSIntegration) -> list[AWSResourceExporterClusterV1]:
    def q(*args: Any, **kwargs: Any) -> dict:
        return fx.get_anymarkup("clusters.yml")

    return intg.get_aws_resource_exporter_clusters(
        q, aws_resource_exporter_clusters=intg.params.aws_resource_exporter_clusters
    )


def test_avs_get_namespaces(namespaces: Sequence[NamespaceV1]) -> None:
    assert len(namespaces) == 2
    assert namespaces[0].name == "namespace-1"
    assert len(namespaces[0].external_resources) == 2  # type: ignore
    assert len(namespaces[0].external_resources[0].resources) == 4  # type: ignore
    assert len(namespaces[0].external_resources[1].resources) == 2  # type: ignore

    assert namespaces[1].name == "namespace-2"
    assert len(namespaces[1].external_resources) == 1  # type: ignore
    assert len(namespaces[1].external_resources[0].resources) == 1  # type: ignore


def test_avs_get_aws_resource_exporter_clusters(
    clusters: Sequence[AWSResourceExporterClusterV1],
) -> None:
    assert len(clusters) == 1
    assert clusters[0].name == "aws-resource-exporter-cluster-1"


def test_avs_get_aws_metrics(
    mocker: MockerFixture,
    clusters: list[AWSResourceExporterClusterV1],
    intg: AVSIntegration,
) -> None:
    def _prom_get_return(
        *args: Any, params: Any, **kwargs: Any
    ) -> list[dict[str, str]]:
        match params:
            case {"query": "aws_resources_exporter_rds_engineversion"}:
                return [
                    {
                        "__name__": "aws_resources_exporter_rds_engineversion",
                        "aws_account_id": "aws_account_id-1",
                        "dbinstance_identifier": "rds-1",
                        "engine": "postgres",
                        "engine_version": "13.10",
                    },
                    {
                        "__name__": "aws_resources_exporter_rds_engineversion",
                        "aws_account_id": "aws_account_id-2",
                        "dbinstance_identifier": "rds-2",
                        "engine": "postgres",
                        "engine_version": "15.2",
                    },
                ]
            case {"query": "aws_resources_exporter_elasticache_redisversion"}:
                return [
                    {
                        "__name__": "aws_resources_exporter_elasticache_redisversion",
                        "aws_account_id": "aws_account_id-1",
                        "replication_group_id": "elasticache-cache-foobar",
                        "engine": "redis",
                        "engine_version": "6.2.4",
                    },
                    {
                        "__name__": "aws_resources_exporter_elasticache_redisversion",
                        "aws_account_id": "aws_account_id-2",
                        "replication_group_id": "elasticache-2",
                        "engine": "redis",
                        "engine_version": "6.2.4",
                    },
                ]
            case _:
                raise ValueError(f"Unexpected params: {params}")

    prom_get_mock = mocker.create_autospec(spec=prom_get, side_effect=_prom_get_return)
    metrics = intg.get_aws_metrics(
        # test also uniquify of clusters
        clusters=clusters + clusters,
        timeout=10,
        elasticache_replication_group_id_to_identifier={
            ("aws_account_id-1", "elasticache-cache-foobar"): "elasticache-1"
        },
        prom_get_func=prom_get_mock,
    )
    assert prom_get_mock.call_count == 2
    assert metrics == [
        ExternalResource(
            namespace_file=None,
            provider="aws",
            provisioner=ExternalResourceProvisioner(uid="aws_account_id-1", path=None),
            resource_provider="rds",
            resource_identifier="rds-1",
            resource_engine="postgres",
            resource_engine_version="13.10",
        ),
        ExternalResource(
            namespace_file=None,
            provider="aws",
            provisioner=ExternalResourceProvisioner(uid="aws_account_id-2", path=None),
            resource_provider="rds",
            resource_identifier="rds-2",
            resource_engine="postgres",
            resource_engine_version="15.2",
        ),
        ExternalResource(
            namespace_file=None,
            provider="aws",
            provisioner=ExternalResourceProvisioner(uid="aws_account_id-1", path=None),
            resource_provider="elasticache",
            resource_identifier="elasticache-1",
            resource_engine="redis",
            resource_engine_version="6.2.4",
        ),
        ExternalResource(
            namespace_file=None,
            provider="aws",
            provisioner=ExternalResourceProvisioner(uid="aws_account_id-2", path=None),
            resource_provider="elasticache",
            resource_identifier="elasticache-2",
            resource_engine="redis",
            resource_engine_version="6.2.4",
        ),
    ]


def test_avs_get_external_resource_specs(
    mocker: MockerFixture,
    namespaces: Sequence[NamespaceV1],
    intg: AVSIntegration,
) -> None:
    gql_mock = mocker.create_autospec(spec=GqlApi)

    def get_resource_return(path: str) -> dict[str, Any]:
        match path:
            case "defaults.yml":
                return {
                    "content": dedent(
                        """
                        ---
                        $schema: /aws/rds-defaults-1.yml
                        engine: postgres
                        engine_version: '13.5'
                        instance_class: db.t3.micro
                        allocated_storage: 20
                    """
                    )
                }
            case "defaults-2.yml":
                return {
                    "content": dedent(
                        """
                        ---
                        $schema: /aws/rds-defaults-1.yml
                        engine: postgres
                        engine_version: '13.1'
                        instance_class: db.t3.micro
                        allocated_storage: 20
                    """
                    )
                }
            case "ec-defaults.yml":
                return {
                    "content": dedent(
                        """
                        ---
                        engine: redis
                        engine_version: '6.2.1'
                        replication_group_id: elasticache-cache-foobar
                    """
                    )
                }
            case "ec-defaults-2.yml":
                # 'elasticache-2' must be irgnored because of '6.x' engine_version
                return {
                    "content": dedent(
                        """
                        ---
                        engine: redis
                        engine_version: '6.x'
                    """
                    )
                }
            case _:
                raise ValueError(f"Unexpected path: {path}")

    gql_mock.get_resource.side_effect = get_resource_return

    eres = intg.get_external_resource_specs(
        gql_get_resource_func=gql_mock.get_resource,
        namespaces=namespaces,
        supported_providers=intg.params.supported_providers,
    )
    assert gql_mock.get_resource.call_count == 4
    assert eres == [
        ExternalResource(
            namespace_file="/namespace-file.yml",
            provider="aws",
            provisioner=ExternalResourceProvisioner(
                uid="account-1", path="account-1.yml"
            ),
            resource_provider="rds",
            resource_identifier="rds-1",
            resource_engine="postgres",
            resource_engine_version="13.5",
        ),
        ExternalResource(
            namespace_file="/namespace-file.yml",
            provider="aws",
            provisioner=ExternalResourceProvisioner(
                uid="account-1", path="account-1.yml"
            ),
            resource_provider="rds",
            resource_identifier="rds-2",
            resource_engine="postgres",
            resource_engine_version="13.1",
        ),
        ExternalResource(
            namespace_file="/namespace-file.yml",
            provider="aws",
            provisioner=ExternalResourceProvisioner(
                uid="account-1", path="account-1.yml"
            ),
            resource_provider="elasticache",
            resource_identifier="elasticache-1",
            resource_engine="redis",
            resource_engine_version="6.2.1",
            redis_replication_group_id="elasticache-cache-foobar",
        ),
        ExternalResource(
            namespace_file="/namespace-file.yml",
            provider="aws",
            provisioner=ExternalResourceProvisioner(
                uid="account-1a", path="account-1a.yml"
            ),
            resource_provider="rds",
            resource_identifier="rds-1",
            resource_engine="postgres",
            resource_engine_version="13.5",
        ),
        ExternalResource(
            namespace_file="/namespace-file.yml",
            provider="aws",
            provisioner=ExternalResourceProvisioner(
                uid="account-1a", path="account-1a.yml"
            ),
            resource_provider="elasticache",
            resource_identifier="elasticache-1",
            resource_engine="redis",
            resource_engine_version="6.2.1",
            redis_replication_group_id="elasticache-cache-foobar",
        ),
        ExternalResource(
            namespace_file="/namespace-file.yml",
            provider="aws",
            provisioner=ExternalResourceProvisioner(
                uid="account-2", path="account-2.yml"
            ),
            resource_provider="rds",
            resource_identifier="rds-1",
            resource_engine="postgres",
            resource_engine_version="13.5",
        ),
    ]


def test_avs_reconcile(mocker: MockerFixture, intg: AVSIntegration) -> None:
    merge_request_manager_mock = mocker.create_autospec(spec=MergeRequestManager)
    no_change_aws = ExternalResource(
        namespace_file=None,
        provider="aws",
        provisioner=ExternalResourceProvisioner(uid="no_change", path=None),
        resource_provider="rds",
        resource_identifier="no_change",
        resource_engine="postgres",
        resource_engine_version="13.5",
    )
    no_change_ai = ExternalResource(
        namespace_file="/no_change_ai-namespace-file.yml",
        provider="aws",
        provisioner=ExternalResourceProvisioner(uid="no_change", path="no_change.yml"),
        resource_provider="rds",
        resource_identifier="no_change",
        resource_engine="postgres",
        resource_engine_version="13.5",
    )
    no_downgrade_aws = ExternalResource(
        namespace_file=None,
        provider="aws",
        provisioner=ExternalResourceProvisioner(uid="no_downgrade", path=None),
        resource_provider="rds",
        resource_identifier="no_downgrade",
        resource_engine="postgres",
        resource_engine_version="13.5",
    )
    no_downgrade_ai = ExternalResource(
        namespace_file="/no_downgrade_ai-namespace-file.yml",
        provider="aws",
        provisioner=ExternalResourceProvisioner(
            uid="no_downgrade", path="no_downgrade.yml"
        ),
        resource_provider="rds",
        resource_identifier="no_downgrade",
        resource_engine="postgres",
        resource_engine_version="13.10",
    )
    version_update_aws = ExternalResource(
        namespace_file=None,
        provider="aws",
        provisioner=ExternalResourceProvisioner(uid="version_update", path=None),
        resource_provider="rds",
        resource_identifier="version_update",
        resource_engine="postgres",
        resource_engine_version="13.1",
    )
    version_update_ai = ExternalResource(
        namespace_file="/version_update_ai-namespace-file.yml",
        provider="aws",
        provisioner=ExternalResourceProvisioner(
            uid="version_update", path="version_update.yml"
        ),
        resource_provider="rds",
        resource_identifier="version_update",
        resource_engine="postgres",
        resource_engine_version="13.0",
    )
    ec_version_update_aws = ExternalResource(
        namespace_file=None,
        provider="aws",
        provisioner=ExternalResourceProvisioner(uid="version_update", path=None),
        resource_provider="elasticache",
        resource_identifier="ec-version_update",
        resource_engine="redis",
        resource_engine_version="13.1",
    )
    ec_version_update_ai = ExternalResource(
        namespace_file="/version_update_ai-namespace-file.yml",
        provider="aws",
        provisioner=ExternalResourceProvisioner(
            uid="version_update", path="version_update.yml"
        ),
        resource_provider="elasticache",
        resource_identifier="ec-version_update",
        resource_engine="redis",
        resource_engine_version="13.0",
    )
    same_name_different_account = ExternalResource(
        namespace_file="/same_name_different_account-namespace-file.yml",
        provider="aws",
        provisioner=ExternalResourceProvisioner(
            uid="just-another-account", path="just-another-account.yml"
        ),
        resource_provider="rds",
        resource_identifier="version_update",
        resource_engine="postgres",
        resource_engine_version="13.1",
    )
    aws_only = ExternalResource(
        namespace_file=None,
        provider="aws",
        provisioner=ExternalResourceProvisioner(uid="account", path=None),
        resource_provider="rds",
        resource_identifier="this-resource-is-only-in-aws",
        resource_engine="postgres",
        resource_engine_version="13.1",
    )
    ai_only = ExternalResource(
        namespace_file="/ai_only-namespace-file.yml",
        provider="aws",
        provisioner=ExternalResourceProvisioner(uid="account", path="account.yml"),
        resource_provider="rds",
        resource_identifier="this-resource-is-only-in-app-interface",
        resource_engine="postgres",
        resource_engine_version="13.1",
    )
    external_resources_aws = [
        no_change_aws,
        version_update_aws,
        aws_only,
        no_downgrade_aws,
        ec_version_update_aws,
    ]

    external_resources_app_interface = [
        no_change_ai,
        version_update_ai,
        same_name_different_account,
        ai_only,
        no_downgrade_ai,
        ec_version_update_ai,
    ]
    # randomize the order of the external resources
    random.shuffle(external_resources_aws)
    random.shuffle(external_resources_app_interface)

    intg.reconcile(
        merge_request_manager=merge_request_manager_mock,
        external_resources_aws=external_resources_aws,
        external_resources_app_interface=external_resources_app_interface,
    )
    merge_request_manager_mock.create_merge_request.assert_has_calls(
        [
            mocker.call(
                MrData(
                    namespace_file=version_update_ai.namespace_file,
                    provider=version_update_ai.provider,
                    provisioner_ref=version_update_ai.provisioner.path,
                    provisioner_uid=version_update_ai.provisioner.uid,
                    resource_provider=version_update_ai.resource_provider,
                    resource_identifier=version_update_ai.resource_identifier,
                    resource_engine=version_update_ai.resource_engine,
                    resource_engine_version="13.1",
                )
            ),
            mocker.call(
                MrData(
                    namespace_file=ec_version_update_ai.namespace_file,
                    provider=ec_version_update_ai.provider,
                    provisioner_ref=ec_version_update_ai.provisioner.path,
                    provisioner_uid=ec_version_update_ai.provisioner.uid,
                    resource_provider=ec_version_update_ai.resource_provider,
                    resource_identifier=ec_version_update_ai.resource_identifier,
                    resource_engine=ec_version_update_ai.resource_engine,
                    resource_engine_version="13.1",
                )
            ),
        ],
        any_order=True,
    )


@pytest.mark.parametrize(
    "er,expected",
    [
        (
            ExternalResource(
                namespace_file="/namespace-file.yml",
                provider="aws",
                provisioner=ExternalResourceProvisioner(
                    uid="account-1", path="account-1.yml"
                ),
                resource_provider="rds",
                resource_identifier="rds-1",
                resource_engine="postgres",
                resource_engine_version="13",
            ),
            "13",
        ),
        (
            ExternalResource(
                namespace_file="/namespace-file.yml",
                provider="aws",
                provisioner=ExternalResourceProvisioner(
                    uid="account-1", path="account-1.yml"
                ),
                resource_provider="rds",
                resource_identifier="rds-1",
                resource_engine="postgres",
                resource_engine_version="13.5",
            ),
            "13.5",
        ),
        (
            ExternalResource(
                namespace_file="/namespace-file.yml",
                provider="aws",
                provisioner=ExternalResourceProvisioner(
                    uid="account-1", path="account-1.yml"
                ),
                resource_provider="rds",
                resource_identifier="rds-1",
                resource_engine="postgres",
                resource_engine_version="13.5.1",
            ),
            "13.5.1",
        ),
    ],
)
def test_external_resources_resource_engine_version_string(
    er: ExternalResource, expected: str
) -> None:
    assert er.resource_engine_version_string == expected
