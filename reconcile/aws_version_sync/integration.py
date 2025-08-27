import logging
from collections.abc import (
    Callable,
    Iterable,
)
from enum import StrEnum
from typing import Any

import semver
from pydantic import (
    BaseModel,
    ValidationError,
    root_validator,
    validator,
)

from reconcile.aws_version_sync.merge_request_manager.merge_request import (
    Renderer,
    create_parser,
)
from reconcile.aws_version_sync.merge_request_manager.merge_request_manager import (
    MergeRequestManager,
    MrData,
)
from reconcile.aws_version_sync.utils import (
    get_values,
    override_values,
    prom_get,
    uniquify,
)
from reconcile.gql_definitions.aws_version_sync.clusters import ClusterV1
from reconcile.gql_definitions.aws_version_sync.clusters import query as clusters_query
from reconcile.gql_definitions.aws_version_sync.namespaces import (
    AWSAccountV1,
    NamespaceTerraformProviderResourceAWSV1,
    NamespaceTerraformResourceElastiCacheV1,
    NamespaceTerraformResourceRDSV1,
    NamespaceV1,
)
from reconcile.gql_definitions.aws_version_sync.namespaces import (
    query as namespaces_query,
)
from reconcile.typed_queries.app_interface_repo_url import get_app_interface_repo_url
from reconcile.typed_queries.github_orgs import get_github_orgs
from reconcile.typed_queries.gitlab_instances import get_gitlab_instances
from reconcile.utils import gql
from reconcile.utils.defer import defer
from reconcile.utils.differ import diff_iterables
from reconcile.utils.disabled_integrations import integration_is_enabled
from reconcile.utils.runtime.integration import (
    PydanticRunParams,
    QontractReconcileIntegration,
)
from reconcile.utils.semver_helper import parse_semver
from reconcile.utils.unleash import get_feature_toggle_state
from reconcile.utils.vcs import VCS

QONTRACT_INTEGRATION = "aws-version-sync"


class AVSIntegrationParams(PydanticRunParams):
    prometheus_timeout: int = 10
    supported_providers: set[str]
    clusters: set[str]
    aws_resource_exporter_clusters: set[str]


class ExternalResourceProvisioner(BaseModel):
    uid: str
    path: str | None = None


class VersionFormat(StrEnum):
    MAJOR = "major"
    MAJOR_MINOR = "major_minor"
    MAJOR_MINOR_PATCH = "major_minor_patch"


class SupportedResourceProvider(StrEnum):
    RDS = "rds"
    ELASTICACHE = "elasticache"


class ExternalResource(BaseModel):
    namespace_file: str | None = None
    provider: str = "aws"
    provisioner: ExternalResourceProvisioner
    resource_provider: SupportedResourceProvider
    resource_identifier: str
    resource_engine: str
    resource_engine_version: semver.VersionInfo
    # if None, it'll be set via root_validator
    resource_engine_version_format: VersionFormat | None = None
    # used to map AWS cache name to resource_identifier
    redis_replication_group_id: str | None = None

    class Config:
        arbitrary_types_allowed = True

    @property
    def key(self) -> tuple:
        return (
            self.provider,
            self.provisioner.uid,
            self.resource_provider,
            self.resource_identifier,
        )

    @validator("resource_engine_version", pre=True)
    def parse_resource_engine_version(
        cls, v: str | semver.VersionInfo
    ) -> semver.VersionInfo:
        if isinstance(v, semver.VersionInfo):
            return v
        return parse_semver(str(v), optional_minor_and_patch=True)

    @root_validator(pre=True)
    def set_resource_engine_version_format(cls, values: dict) -> dict:
        resource_engine_version, resource_engine_version_format = (
            str(values.get("resource_engine_version")),
            values.get("resource_engine_version_format"),
        )
        if not resource_engine_version:
            # make mypy happy
            raise ValueError("resource_engine_version is required")

        if resource_engine_version_format is None:
            match resource_engine_version.count("."):
                case 0:
                    values["resource_engine_version_format"] = VersionFormat.MAJOR
                case 1:
                    values["resource_engine_version_format"] = VersionFormat.MAJOR_MINOR
                case 2:
                    values["resource_engine_version_format"] = (
                        VersionFormat.MAJOR_MINOR_PATCH
                    )
                case _:
                    raise ValueError(
                        f"Invalid version format: {resource_engine_version}"
                    )
        if values.get("resource_provider") == SupportedResourceProvider.ELASTICACHE:
            if resource_engine_version.startswith("5"):
                # AWS ElastiCache Redis 5 uses MAJOR_MINOR_PATCH format
                values["resource_engine_version_format"] = (
                    VersionFormat.MAJOR_MINOR_PATCH
                )
            else:
                # AWS ElastiCache Redis 6+ uses MAJOR_MINOR format
                values["resource_engine_version_format"] = VersionFormat.MAJOR_MINOR
        return values

    @property
    def resource_engine_version_string(self) -> str:
        match self.resource_engine_version_format:
            case VersionFormat.MAJOR:
                return f"{self.resource_engine_version.major}"
            case VersionFormat.MAJOR_MINOR:
                return f"{self.resource_engine_version.major}.{self.resource_engine_version.minor}"
            case VersionFormat.MAJOR_MINOR_PATCH:
                return f"{self.resource_engine_version.major}.{self.resource_engine_version.minor}.{self.resource_engine_version.patch}"
            case _:
                raise ValueError(
                    f"Invalid version format: {self.resource_engine_version_format}"
                )


AwsExternalResources = list[ExternalResource]
AppInterfaceExternalResources = list[ExternalResource]
UidAndReplicationGroupId = tuple[str, str]
ReplicationGroupIdToIdentifier = dict[UidAndReplicationGroupId, str]
EXTENDED_SUPPORT_VERSION_INDICATOR = "-rds."


class AVSIntegration(QontractReconcileIntegration[AVSIntegrationParams]):
    """Update AWS asset version numbers (in App-Interface) based on AWS resource exporter metrics.

    This integration fetches the latest version numbers of AWS assets from AWS
    resource exporter metrics and updates the version numbers in the App-Interface
    via MRs.
    """

    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    def get_namespaces(
        self, query_func: Callable, clusters: Iterable[str]
    ) -> list[NamespaceV1]:
        data = namespaces_query(query_func)
        namespaces = []

        for ns in data.namespaces or []:
            if (
                integration_is_enabled(QONTRACT_INTEGRATION, ns.cluster)
                and ns.managed_external_resources
            ):
                if clusters:
                    if ns.cluster.name in clusters:
                        namespaces.append(ns)
                else:
                    # no clusters specified, so include all namespaces from all clusters
                    namespaces.append(ns)

        return namespaces

    def get_aws_resource_exporter_clusters(
        self, query_func: Callable, aws_resource_exporter_clusters: Iterable[str]
    ) -> list[ClusterV1]:
        data = clusters_query(query_func)
        return [
            cluster
            for cluster in data.clusters or []
            if cluster.name in aws_resource_exporter_clusters
            and integration_is_enabled(QONTRACT_INTEGRATION, cluster)
        ]

    def get_aws_metrics(
        self,
        clusters: Iterable[ClusterV1],
        timeout: int,
        elasticache_replication_group_id_to_identifier: ReplicationGroupIdToIdentifier,
        supported_providers: Iterable[str],
        prom_get_func: Callable = prom_get,
    ) -> list[ExternalResource]:
        metrics: list[ExternalResource] = []
        # compile a list of all RDS metrics from all AWS resource exporter clusters; ignore duplicated clusters
        for cluster in uniquify(key=lambda c: c.name, items=clusters):
            token = (
                self.secret_reader.read_secret(cluster.automation_token)
                if cluster.automation_token
                else None
            )

            # RDS resources
            if SupportedResourceProvider.RDS in supported_providers:
                metrics.extend(
                    self._fetch_rds_metrics(cluster, token, timeout, prom_get_func)
                )

            # ElastiCache resources
            if SupportedResourceProvider.ELASTICACHE in supported_providers:
                metrics.extend(
                    self._fetch_elasticache_metrics(
                        cluster,
                        token,
                        timeout,
                        elasticache_replication_group_id_to_identifier,
                        prom_get_func,
                    )
                )

        return metrics

    def _fetch_rds_metrics(
        self,
        cluster: ClusterV1,
        token: str | None,
        timeout: int,
        prom_get_func: Callable,
    ) -> list[ExternalResource]:
        """Fetch RDS metrics from the AWS resource exporter."""
        metrics: list[ExternalResource] = []
        try:
            rds_metrics = prom_get_func(
                url=cluster.prometheus_url,
                params={"query": "aws_resources_exporter_rds_engineversion"},
                token=token,
                timeout=timeout,
            )
        except Exception as e:
            logging.error(
                f"Failed to get 'aws_resources_exporter_rds_engineversion' metrics for cluster {cluster.name}: {e}"
            )
            return []

        for m in rds_metrics:
            try:
                metrics.append(
                    ExternalResource(
                        provider="aws",
                        provisioner=ExternalResourceProvisioner(
                            uid=m["aws_account_id"]
                        ),
                        resource_provider=SupportedResourceProvider.RDS,
                        resource_identifier=m["dbinstance_identifier"],
                        resource_engine=m["engine"],
                        resource_engine_version=m["engine_version"],
                    )
                )
            except ValidationError as e:
                if EXTENDED_SUPPORT_VERSION_INDICATOR in m["engine_version"]:
                    # don't try to parse AWS extended support version numbers
                    # See https://aws.amazon.com/about-aws/whats-new/2025/04/amazon-rds-postgresql-extended-support-11-22-rds-20250220-12-22-rds-20250220/ for more info
                    pass
                else:
                    logging.error(
                        f"Failed to parse RDS metric for {m['dbinstance_identifier']}: {e}"
                    )
            except KeyError as e:
                logging.error(
                    f"Failed to parse RDS metric for {m['dbinstance_identifier']}: {e}"
                )
        return metrics

    def _fetch_elasticache_metrics(
        self,
        cluster: ClusterV1,
        token: str | None,
        timeout: int,
        elasticache_replication_group_id_to_identifier: ReplicationGroupIdToIdentifier,
        prom_get_func: Callable,
    ) -> list[ExternalResource]:
        """Fetch ElastiCache metrics from the AWS resource exporter."""
        metrics: list[ExternalResource] = []
        try:
            elasticache_metrics = prom_get_func(
                url=cluster.prometheus_url,
                params={"query": "aws_resources_exporter_elasticache_redisversion"},
                token=token,
                timeout=timeout,
            )
        except Exception as e:
            logging.error(
                f"Failed to get 'aws_resources_exporter_elasticache_redisversion' metrics for cluster {cluster.name}: {e}"
            )
            return []

        for m in elasticache_metrics:
            try:
                metrics.append(
                    ExternalResource(
                        provider="aws",
                        provisioner=ExternalResourceProvisioner(
                            uid=m["aws_account_id"]
                        ),
                        resource_provider=SupportedResourceProvider.ELASTICACHE,
                        # replication_group_id != resource_identifier!
                        resource_identifier=elasticache_replication_group_id_to_identifier.get(
                            (
                                m["aws_account_id"],
                                m["replication_group_id"],
                            ),
                            m["replication_group_id"],
                        ),
                        resource_engine=m["engine"],
                        resource_engine_version=m["engine_version"],
                    )
                )
            except (ValidationError, KeyError) as e:
                logging.error(
                    f"Failed to parse ElastiCache metrics for {m['replication_group_id']}: {e}"
                )

        return metrics

    def get_external_resource_specs(
        self,
        gql_get_resource_func: Callable,
        namespaces: Iterable[NamespaceV1],
        supported_providers: Iterable[str],
    ) -> list[ExternalResource]:
        external_resources: list[ExternalResource] = []
        defaults_cache: dict[str, Any] = {}
        for ns in namespaces:
            for external_resource in ns.external_resources or []:
                if not isinstance(
                    external_resource, NamespaceTerraformProviderResourceAWSV1
                ):
                    continue
                # make mypy happy
                assert isinstance(external_resource.provisioner, AWSAccountV1)

                for resource in external_resource.resources or []:
                    if resource.provider.lower() not in supported_providers:
                        continue

                    # make mypy happy
                    assert isinstance(
                        resource,
                        NamespaceTerraformResourceElastiCacheV1
                        | NamespaceTerraformResourceRDSV1,
                    )

                    values = {}
                    # get/set the defaults file values from/to cache
                    if resource.defaults:
                        if not (values := defaults_cache.get(resource.defaults, {})):
                            # retrieve the external resource spec values
                            values = get_values(
                                gql_get_resource_func, resource.defaults
                            )
                            defaults_cache[resource.defaults] = values
                    values = override_values(values, resource.overrides)
                    if (
                        resource.provider == SupportedResourceProvider.ELASTICACHE
                        and str(values["engine_version"]).lower().endswith("x")
                    ):
                        # AWS ElastiCache Redis 6 could use a version like 6.x. Let's patch it to a fix version
                        values["engine_version"] = "6.2"

                    if (
                        resource.provider == SupportedResourceProvider.RDS
                        and EXTENDED_SUPPORT_VERSION_INDICATOR
                        in values["engine_version"]
                    ):
                        # AWS RDS PostgreSQL 11 and 12 extended support versions are not supported by this integration
                        # See https://aws.amazon.com/about-aws/whats-new/2025/04/amazon-rds-postgresql-extended-support-11-22-rds-20250220-12-22-rds-20250220/
                        continue

                    external_resources.append(
                        ExternalResource(
                            namespace_file=ns.path,
                            provisioner=ExternalResourceProvisioner(
                                uid=external_resource.provisioner.uid,
                                path=external_resource.provisioner.path,
                            ),
                            resource_provider=resource.provider,
                            resource_identifier=resource.identifier,
                            resource_engine=values["engine"],
                            resource_engine_version=values["engine_version"],
                            redis_replication_group_id=values.get(
                                "replication_group_id", resource.identifier
                            )
                            if resource.provider.lower() == "elasticache"
                            else None,
                        )
                    )

        return external_resources

    def reconcile(
        self,
        merge_request_manager: MergeRequestManager,
        external_resources_aws: AwsExternalResources,
        external_resources_app_interface: AppInterfaceExternalResources,
    ) -> None:
        # housekeeping: close old/bad MRs
        merge_request_manager.housekeeping()
        diff = diff_iterables(
            current=external_resources_app_interface,
            desired=external_resources_aws,
            key=lambda r: r.key,
            equal=lambda external_resources_app_interface,
            external_resources_aws: external_resources_app_interface.resource_engine_version_string
            == external_resources_aws.resource_engine_version_string
            and external_resources_app_interface.resource_engine
            == external_resources_aws.resource_engine,
        )
        for diff_pair in diff.change.values():
            aws_resource = diff_pair.desired
            app_interface_resource = diff_pair.current
            if (
                aws_resource.resource_engine_version
                <= app_interface_resource.resource_engine_version
                and aws_resource.resource_engine
                == app_interface_resource.resource_engine
            ):
                # do not downgrade the version
                continue
            # make mypy happy
            assert app_interface_resource.namespace_file
            assert app_interface_resource.provisioner.path
            merge_request_manager.create_merge_request(
                MrData(
                    namespace_file=app_interface_resource.namespace_file,
                    provider=app_interface_resource.provider,
                    provisioner_ref=app_interface_resource.provisioner.path,
                    provisioner_uid=app_interface_resource.provisioner.uid,
                    resource_provider=app_interface_resource.resource_provider,
                    resource_identifier=app_interface_resource.resource_identifier,
                    resource_engine=aws_resource.resource_engine,
                    resource_engine_version=aws_resource.resource_engine_version_string,
                )
            )

    @defer
    def run(self, dry_run: bool, defer: Callable | None = None) -> None:
        gql_api = gql.get_api()
        vcs = VCS(
            secret_reader=self.secret_reader,
            github_orgs=get_github_orgs(),
            gitlab_instances=get_gitlab_instances(),
            app_interface_repo_url=get_app_interface_repo_url(),
            dry_run=dry_run,
            allow_deleting_mrs=get_feature_toggle_state(
                integration_name=f"{self.name}-allow-deleting-mrs", default=False
            ),
            allow_opening_mrs=get_feature_toggle_state(
                integration_name=f"{self.name}-allow-opening-mrs", default=False
            ),
        )
        if defer:
            defer(vcs.cleanup)
        merge_request_manager = MergeRequestManager(
            vcs=vcs,
            renderer=Renderer(),
            parser=create_parser(),
            auto_merge_enabled=get_feature_toggle_state(
                integration_name=f"{self.name}-allow-auto-merge-mrs", default=False
            ),
        )

        namespaces = self.get_namespaces(gql_api.query, clusters=self.params.clusters)
        aws_resource_exporter_clusters = self.get_aws_resource_exporter_clusters(
            gql_api.query,
            self.params.aws_resource_exporter_clusters,
        )
        external_resources_app_interface = self.get_external_resource_specs(
            gql_api.get_resource,
            namespaces,
            supported_providers=self.params.supported_providers,
        )
        external_resources_aws = self.get_aws_metrics(
            aws_resource_exporter_clusters,
            timeout=self.params.prometheus_timeout,
            elasticache_replication_group_id_to_identifier={
                (
                    external_resource.provisioner.uid,
                    external_resource.redis_replication_group_id,
                ): external_resource.resource_identifier
                for external_resource in external_resources_app_interface
                if external_resource.redis_replication_group_id
            },
            supported_providers=self.params.supported_providers,
        )

        self.reconcile(
            merge_request_manager=merge_request_manager,
            external_resources_aws=external_resources_aws,
            external_resources_app_interface=external_resources_app_interface,
        )
