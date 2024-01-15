from typing import Optional

from pydantic import BaseModel

from reconcile.utils.acs.base import AcsBaseApi


class Scope(BaseModel):
    cluster: str
    namespace: Optional[str]


class PolicyCondition(BaseModel):
    field_name: str
    negate: bool
    values: list[str]


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
            c.cluster_id: c.name for c in self.get_cluster_identifiers()
        }
        # make individual policy requests to obtain further details
        custom_policies_api_result = [
            self.generic_request(f"/v1/policies/{pid}", "GET").json()
            for pid in custom_policy_ids
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
                    categories=sorted(cp["categories"]),
                    severity=cp["severity"],
                    scope=sorted(
                        [
                            Scope(
                                cluster=cluster_ids_names[s["cluster"]],
                                namespace=s["namespace"],
                            )
                            for s in cp["scope"]
                        ],
                        key=lambda s: s.cluster,
                    ),
                    conditions=conditions,
                )
            )
        return formatted_custom_policies

    class ClusterIdentifiers(BaseModel):
        name: str
        cluster_id: str

    def get_cluster_identifiers(self) -> list[ClusterIdentifiers]:
        return [
            self.ClusterIdentifiers(name=c["name"], cluster_id=c["id"])
            for c in self.generic_request("/v1/clusters", "GET").json()["clusters"]
        ]
    
    def get_custom_policy_id_names(self) -> dict[str, str]:
        return {
            p["name"]: p["id"]
            for p in self.generic_request("/v1/policies", "GET").json()["policies"]
            if not p["isDefault"]
        }

    def create_policy(self, to_add: Policy) -> None:
        body = {
            "name": to_add.name,
            "description": to_add.description,
            "categories": to_add.categories,
            "severity": to_add.severity,
            "isDefault": False,
            "disabled": False,
            "scope": [
                {"cluster": s.cluster, "namespace": s.namespace} for s in to_add.scope
            ],
            "lifecycleStages": [
                "BUILD"
            ],  # all currently supported policy criteria are classified as 'build' stage
            "policySections": [
                {
                    "sectionName": "primary",
                    "policyGroups": [
                        {
                            "fieldName": c.field_name,
                            "negate": c.negate,
                            "values": [{"value": v} for v in c.values],
                        }
                        for c in to_add.conditions
                    ],
                }
            ],
        }
        self.generic_request("/v1/policies", "POST", body)

    def delete_policy(self, id: str) -> None:
        self.generic_request(f"/v1/policies/{id}", "DELETE")

    def update_policy(self, to_update: Policy):
        pass
