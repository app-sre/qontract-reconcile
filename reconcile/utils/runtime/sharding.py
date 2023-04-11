import copy

from dataclasses import dataclass
from typing import Optional, Protocol, Iterable, Union
from pydantic import BaseModel
from reconcile.utils.runtime.meta import IntegrationMeta
from reconcile.gql_definitions.common import clusters_minimal
from reconcile.gql_definitions.common.clusters_minimal import ClusterV1

from reconcile.gql_definitions.sharding import aws_accounts as sharding_aws_accounts


from reconcile.gql_definitions.terraform_cloudflare_dns import (
    terraform_cloudflare_zones,
)
from reconcile.gql_definitions.terraform_cloudflare_dns.terraform_cloudflare_zones import (
    CloudflareDnsZoneV1,
)

from reconcile.utils import gql

from reconcile.gql_definitions.integrations.integrations import (
    IntegrationShardingV1,
    IntegrationManagedV1,
    IntegrationSpecV1,
    OpenshiftClusterShardSpecOverrideV1,
    AWSAccountShardSpecOverrideV1,
    CloudflareDNSZoneShardSpecOverrideV1,
    StaticShardingV1,
    SubShardingV1,
    StaticSubShardingV1,
    OpenshiftClusterShardingV1,
    AWSAccountShardingV1,
    CloudflareDNSZoneShardingV1,
)


class ShardSpec(BaseModel):
    # Base Sharding
    shards: Optional[str] = ""
    shard_id: Optional[str] = ""
    shard_spec_overrides: Optional[
        Union[
            AWSAccountShardSpecOverrideV1,
            OpenshiftClusterShardSpecOverrideV1,
            CloudflareDNSZoneShardSpecOverrideV1,
        ]
    ] = None

    # Key sharding
    shard_key: str = ""
    shard_name_suffix: str = ""
    extra_args: str = ""

    def add_extra_args(self, args: str) -> None:
        if args:
            self.extra_args += f" {args}"


class ShardingStrategy(Protocol):
    def build_integration_shards(
        self,
        integration_meta: IntegrationMeta,
        integration_managed: IntegrationManagedV1,
    ) -> list[ShardSpec]:
        pass


class SubShardingStrategy(Protocol):
    @staticmethod
    def create_sub_shards(
        base_shard: ShardSpec, sub_sharding: SubShardingV1
    ) -> list[ShardSpec]:
        pass


class StaticShardingStrategy:
    IDENTIFIER = "static"

    def build_integration_shards(
        self, _: IntegrationMeta, integration_spec: IntegrationManagedV1
    ) -> list[ShardSpec]:
        shards = 1
        if integration_spec.sharding and isinstance(
            integration_spec.sharding, StaticShardingV1
        ):
            shards = integration_spec.sharding.shards

        return [
            ShardSpec(
                shard_id=str(s),
                shards=str(shards),
                shard_name_suffix=f"-{s}" if shards > 1 else "",
                extra_args="",
            )
            for s in range(0, shards)
        ]

    @staticmethod
    def create_sub_shards(
        base_shard: ShardSpec, sub_sharding: SubShardingV1
    ) -> list[ShardSpec]:
        if base_shard.shard_id != "" or base_shard.shards != "":
            raise ValueError(
                "Static sub_sharding can only be applied to Key based sharding"
            )
        else:
            num_shards = 1
            if isinstance(sub_sharding, StaticSubShardingV1):
                num_shards = sub_sharding.shards
            shards: list[ShardSpec] = []

            for s in range(0, num_shards):
                new_shard = copy.deepcopy(base_shard)
                if new_shard.shard_spec_overrides and isinstance(
                    new_shard.shard_spec_overrides, OpenshiftClusterShardSpecOverrideV1
                ):
                    new_shard.shard_spec_overrides.sub_sharding = None
                new_shard.shard_id = str(s)
                new_shard.shards = str(num_shards)
                new_shard.shard_name_suffix += f"-{s}"
                shards.append(new_shard)
            return shards


class AWSAccountShardingStrategy:
    IDENTIFIER = "per-aws-account"

    def __init__(
        self,
        aws_accounts: Optional[Iterable[sharding_aws_accounts.AWSAccountV1]] = None,
    ):

        if not aws_accounts:
            self.aws_accounts = (
                sharding_aws_accounts.query(query_func=gql.get_api().query).aws_accounts
                or []
            )
        else:
            self.aws_accounts = list(aws_accounts)

    def filter_accounts(
        self, integration: str
    ) -> list[sharding_aws_accounts.AWSAccountV1]:
        return [
            a
            for a in self.aws_accounts
            if (
                not a.disable
                or not a.disable.integrations
                or (
                    a.disable.integrations and integration not in a.disable.integrations
                )
            )
        ]

    def get_shard_spec_overrides(
        self, sharding: Optional[IntegrationShardingV1]
    ) -> dict[str, AWSAccountShardSpecOverrideV1]:

        spos: dict[str, AWSAccountShardSpecOverrideV1] = {}

        if isinstance(sharding, AWSAccountShardingV1) and sharding.shard_spec_overrides:
            for sp in sharding.shard_spec_overrides:
                spos[sp.shard.name] = sp
        return spos

    def check_integration_sharding_params(self, meta: IntegrationMeta) -> None:
        if "--account-name" not in meta.args:
            raise ValueError(
                f"integration {meta.name} does not support the provided argument. "
                " --account-name is required by the 'per-aws-account' sharding "
                "strategy."
            )

    def build_shard_spec(
        self,
        aws_account: sharding_aws_accounts.AWSAccountV1,
        integration_spec: IntegrationSpecV1,
        spo: Optional[AWSAccountShardSpecOverrideV1],
    ) -> ShardSpec:

        return ShardSpec(
            shard_key=aws_account.name,
            shard_name_suffix=f"-{aws_account.name}",
            extra_args=(integration_spec.extra_args or "")
            + f" --account-name {aws_account.name}",
            shard_spec_overrides=spo,
        )

    def build_integration_shards(
        self,
        integration_meta: IntegrationMeta,
        integration_managed: IntegrationManagedV1,
    ) -> list[ShardSpec]:

        self.check_integration_sharding_params(integration_meta)
        spos = self.get_shard_spec_overrides(integration_managed.sharding)
        shards = []
        for c in self.filter_accounts(integration_meta.name):
            spo = spos.get(c.name)
            base_shard = self.build_shard_spec(c, integration_managed.spec, spo)
            shards.append(base_shard)
        return shards


class OpenshiftClusterShardingStrategy:
    IDENTIFIER = "per-openshift-cluster"

    def __init__(self, clusters: Optional[Iterable[ClusterV1]] = None):

        if not clusters:
            self.results = (
                clusters_minimal.query(query_func=gql.get_api().query).clusters or []
            )
        else:
            self.clusters = list(clusters)

        self.sub_sharding_strategies = {
            StaticShardingStrategy.IDENTIFIER: StaticShardingStrategy
        }

    def get_shard_spec_overrides(
        self, sharding: Optional[IntegrationShardingV1]
    ) -> dict[str, OpenshiftClusterShardSpecOverrideV1]:

        spos: dict[str, OpenshiftClusterShardSpecOverrideV1] = {}

        if (
            isinstance(sharding, OpenshiftClusterShardingV1)
            and sharding.shard_spec_overrides
        ):
            for sp in sharding.shard_spec_overrides:
                spos[sp.shard.name] = sp
        return spos

    def check_integration_sharding_params(self, meta: IntegrationMeta) -> None:
        if "--cluster-name" not in meta.args:
            raise ValueError(
                f"integration {meta.name} does not support the provided argument. "
                " --cluster-name is required by the 'per-openshift-cluster' sharding "
                "strategy."
            )

    def build_shard_spec(
        self,
        cluster: ClusterV1,
        integration_spec: IntegrationSpecV1,
        spo: Optional[OpenshiftClusterShardSpecOverrideV1],
    ) -> ShardSpec:

        return ShardSpec(
            shard_key=cluster.name,
            shard_name_suffix=f"-{cluster.name}",
            extra_args=(integration_spec.extra_args or "")
            + f" --cluster-name {cluster.name}",
            shard_spec_overrides=spo,
        )

    def build_sub_shards(
        self, base_shard: ShardSpec, spo: Optional[OpenshiftClusterShardSpecOverrideV1]
    ) -> list[ShardSpec]:
        sub_shards = []
        if spo and spo.sub_sharding and spo.sub_sharding.strategy:
            if spo.sub_sharding.strategy not in self.sub_sharding_strategies:
                raise ValueError(
                    "Subsharding strategy not allowed by {self.__class__.__name__}"
                )
            else:
                c = self.sub_sharding_strategies[spo.sub_sharding.strategy]
                sub_shards = c.create_sub_shards(base_shard, spo.sub_sharding)
        return sub_shards

    def build_integration_shards(
        self,
        integration_meta: IntegrationMeta,
        integration_managed: IntegrationManagedV1,
    ) -> list[ShardSpec]:

        self.check_integration_sharding_params(integration_meta)
        spos = self.get_shard_spec_overrides(integration_managed.sharding)
        shards = []
        for c in self.clusters or []:
            spo = spos.get(c.name)
            base_shard = self.build_shard_spec(c, integration_managed.spec, spo)
            sub_shards = self.build_sub_shards(base_shard, spo)
            if sub_shards:
                shards.extend(sub_shards)
            else:
                shards.append(base_shard)
        return shards


class CloudflareDnsZoneShardingStrategy:
    """
    This provides a new sharding strategy that each shard is targeting a Cloudflare zone.
    It uses the combination of the Cloudflare account name and the zone's identifier as the unique sharding key.
    """

    IDENTIFIER = "per-cloudflare-dns-zone"

    def __init__(
        self, cloudflare_zones: Optional[Iterable[CloudflareDnsZoneV1]] = None
    ):
        if not cloudflare_zones:
            self.cloudflare_zones = (
                terraform_cloudflare_zones.query(query_func=gql.get_api().query).zones
                or []
            )
        else:
            self.cloudflare_zones = list(cloudflare_zones)

    def _get_shard_key(self, dns_zone: CloudflareDnsZoneV1) -> str:
        return f"{dns_zone.account.name}-{dns_zone.identifier}"

    def get_shard_spec_overrides(
        self, sharding: Optional[IntegrationShardingV1]
    ) -> dict[str, CloudflareDNSZoneShardSpecOverrideV1]:

        spos: dict[str, CloudflareDNSZoneShardSpecOverrideV1] = {}

        if (
            isinstance(sharding, CloudflareDNSZoneShardingV1)
            and sharding.shard_spec_overrides
        ):
            for override in sharding.shard_spec_overrides:
                key = f"{override.shard.zone}-{override.shard.identifier}"
                spos[key] = override
        return spos

    def check_integration_sharding_params(self, meta: IntegrationMeta) -> None:
        if "--zone-name" not in meta.args:
            raise ValueError(
                f"integration {meta.name} does not support the provided argument. "
                f"--zone-name is required by the '{self.IDENTIFIER}' sharding "
                "strategy."
            )

    def build_shard_spec(
        self,
        dns_zone: CloudflareDnsZoneV1,
        integration_spec: IntegrationSpecV1,
        spo: Optional[CloudflareDNSZoneShardSpecOverrideV1],
    ) -> ShardSpec:

        return ShardSpec(
            shard_key=self._get_shard_key(dns_zone),
            shard_name_suffix=f"-{self._get_shard_key(dns_zone)}",
            extra_args=(integration_spec.extra_args or "")
            + f" --zone-name {dns_zone.identifier}",
            shard_spec_overrides=spo,
        )

    def build_integration_shards(
        self,
        integration_meta: IntegrationMeta,
        integration_managed: IntegrationManagedV1,
    ) -> list[ShardSpec]:

        self.check_integration_sharding_params(integration_meta)
        spos = self.get_shard_spec_overrides(integration_managed.sharding)
        shards = []
        for zone in self.cloudflare_zones or []:
            spo = spos.get(self._get_shard_key(zone))
            base_shard = self.build_shard_spec(zone, integration_managed.spec, spo)
            shards.append(base_shard)
        return shards


@dataclass
class IntegrationShardManager:

    strategies: dict[str, ShardingStrategy]
    integration_runtime_meta: dict[str, IntegrationMeta]

    def build_integration_shards(
        self, integration: str, integration_spec: IntegrationManagedV1
    ) -> list[ShardSpec]:
        shards: list[ShardSpec] = []

        sharding = integration_spec.sharding
        if not sharding:
            sharding = StaticShardingV1(strategy="static", shards=1)

        integration_meta = self.integration_runtime_meta.get(integration)
        if not integration_meta:
            # workaround until we can get metadata for non cli.py based integrations
            integration_meta = IntegrationMeta(
                name=integration, args=[], short_help=None
            )

        shards = self.strategies[sharding.strategy].build_integration_shards(
            integration_meta, integration_spec
        )
        return shards


# class KeyBasedSharding(ShardingStrategy):
#     def __init__(
#         self,
#         objects: Optional[Sequence],
#         integ_sharding_param: str,
#         sub_sharding_strategies: Mapping[str, Type],
#     ):
#         self.objects = objects
#         self.integ_sharding_param = integ_sharding_param
#         self.sub_sharding_strategies = sub_sharding_strategies

#     @abstractmethod
#     def get_sharding_key(self, obj: Any) -> str:
#         pass

#     @abstractmethod
#     def get_sharding_key_from_spo(self, spo: Any) -> str:
#         pass

#     def get_shard_name_suffix(self, obj: Any) -> str:
#         return f"-{self.get_sharding_key(obj)}"

#     def get_integation_sharding_params(self, obj: Any) -> str:
#         return f"--{self.integ_sharding_param} {self.get_sharding_key(obj)}"

#     def build_shard_spec(
#         self, obj: Any, integration_spec: IntegrationSpecV1
#     ) -> ShardSpec:

#         return ShardSpec(
#             shard_key=self.get_sharding_key(obj),
#             shard_name_suffix=self.get_shard_name_suffix(obj),
#             extra_args=(integration_spec.extra_args or "")
#             + self.get_shard_integration_params(obj),
#             # shard_spec_overrides=shard_spec_overrides,
#         )

#     # def get_spos(self, sharding: IntegrationShardingV1) -> dict[str, Any]:
#     #     spos: dict[str, Any] = {}
#     #     if (
#     #         not isinstance(sharding, (IntegrationShardingV1, StaticShardingV1))
#     #         and sharding.shard_spec_overrides
#     #     ):

#     #         for sp in sharding.shard_spec_overrides:
#     #             spo_shard_id = self.get_shard_spec_override_shard_id(sp)
#     #             spos[spo_shard_id] = sp
#     #     return spos

#     def build_integration_shards(
#         self, integration_meta: IntegrationMeta, integration_spec: IntegrationManagedV1
#     ) -> list[ShardSpec]:

#         # Check if the integration have the necessary params for the sharding strategy
#         # self.check_integration_sharding_params(integration_meta)

#         # Get the shard spec overrides
#         # spos = self.get_shard_spec_overrides(managed.sharding)

#         if f"--{self.integ_sharding_param}" not in integration_meta.args:
#             raise ValueError(
#                 f"integration {integration_meta.name} does not support the provided argument. --{self.integ_sharding_param} is required by the {self.__class__.__name__} sharding strategy."
#             )
#         else:
#             spos = self.get_shard_spec_overrides(integration_spec.sharding)
#             obj_shards = []
#             for obj in self.objects or []:
#                 base_shard = self.build_shard_spec(obj, integration_spec.spec)

#                 sharding_key = self.get_sharding_key(obj)
#                 spo = spos.get(sharding_key)
#                 sub_shards = self.build_sub_shards(base_shard, spo)
#                 if sub_shards:
#                     obj_shards.extend(sub_shards)
#                 else:
#                     obj_shards.append(base_shard)

#             return obj_shards

#     def _filter_objects(self, integration_name: str) -> list[Any]:
#         """Generic function to filter which objects to use. Since the "disable" attribute
#         is used widely, this function is used as a base

#         :param integration_meta: _description_
#         :param spec: _description_
#         :return: Filtered list with the shard objects
#         """
#         filtered = []
#         if self.objects:
#             filtered = [
#                 o
#                 for o in self.objects
#                 if not (o.get("disable") or {})
#                 or "integrations" not in (o.get("disable") or {})
#                 or integration_name not in (o["disable"]["integrations"] or [])
#             ]
#         return filtered

#     @abstractmethod
#     def build_sub_shards(self, base_shard: ShardSpec, spo: Any) -> list[ShardSpec]:
#         pass

#     def get_shard_spec_overrides(
#         self, sharding: Optional[IntegrationShardingV1]
#     ) -> dict[str, SPO]:

#         spos: dict[str, SPO] = {}

#         if isinstance(sharding, KBS) and sharding.shard_spec_override:
#             for sp in sharding.shard_spec_overrides:
#                 spos[sp.shard.name] = sp
#         return spos
