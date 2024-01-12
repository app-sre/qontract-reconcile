from typing import Optional

from pydantic import BaseModel

from reconcile.utils.acs.base import AcsBaseApi


class Scope(BaseModel):
    cluster: str
    namespace: Optional[str]


class PolicyCondition(BaseModel):
    field_name: str
    negate: Optional[bool]
    values: Optional[list[str]]


class Policy(BaseModel):
    name: str
    description: str
    categories: list[str]
    severity: str
    scope: list[Scope]
    conditions: list[PolicyCondition]


class AcsPolicyApi(AcsBaseApi):
    def get_custom_policies(self) -> list[Policy]:
        # retrieve summary data for each policy
        # ignore system default policies from reconciliation
        custom_policy_ids = [
            p["id"]
            for p in self.generic_request("/v1/policies", "GET").json()["policies"]
            if not p["isDefault"]
        ]
        # the 'scope' attribute for each 'policy' references clusters by internal UUIDs
        cluster_ids_names: dict[str, str] = {
            c.cluster_id: c.name for c in self.get_clusters()
        }
        # make individual policy requests to obtain further details
        custom_policies_api_result = [
            self.generic_request(f"/v1/policies/{pid}", "GET").json() for pid in custom_policy_ids
        ]

        formatted_custom_policies: list[Policy] = []
        for cp in custom_policies_api_result:
            conditions: list[PolicyCondition] = []
            for section in cp["policySections"]:
                for group in section.get("policyGroups", []):
                    conditions.append(
                        PolicyCondition(
                            field_name=group["fieldName"],
                            values=[v["value"] for v in group["values"]],
                            negate=group["negate"],
                        )
                    )

            formatted_custom_policies.append(
                Policy(
                    name=cp["name"],
                    description=cp["description"],
                    categories=cp["categories"],
                    severity=cp["severity"],
                    scope=[
                        Scope(
                            cluster=cluster_ids_names[s["cluster"]],
                            namespace=s["namespace"],
                        )
                        for s in cp["scope"]
                    ],
                    conditions=conditions,
                )
            )
        return formatted_custom_policies

    class ClusterIdentifiers(BaseModel):
        name: str
        cluster_id: str

    def get_clusters(self) -> list[ClusterIdentifiers]:
        # each cluster object in response from `/v1/clusters` is unnecessarily detailed for needs
        # of this api. The required attributes are copied over to dedicated lightweight objects
        return [
            self.ClusterIdentifiers(name=c["name"], cluster_id=c["id"])
            for c in self.generic_request("/v1/clusters", "GET").json()["clusters"]
        ]
