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
    notifiers: list[str]
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
                    notifiers=sorted(cp["notifiers"]),
                    categories=sorted(cp["categories"]),
                    severity=cp["severity"],
                    scope=sorted(
                        [
                            Scope(
                                cluster=s["cluster"],
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

    def get_custom_policy_id_names(self) -> dict[str, str]:
        return {
            p["name"]: p["id"]
            for p in self.generic_request("/v1/policies", "GET").json()["policies"]
            if not p["isDefault"]
        }

    def create_or_update_policy(self, desired: Policy, id: str = "") -> None:
        body = {
            "name": desired.name,
            "description": desired.description,
            "categories": desired.categories,
            "severity": desired.severity,
            "notifiers": desired.notifiers,
            "isDefault": False,
            "disabled": False,
            "scope": [
                {"cluster": s.cluster, "namespace": s.namespace} for s in desired.scope
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
                        for c in desired.conditions
                    ],
                }
            ],
        }
        if id:
            self.generic_request(f"/v1/policies/{id}", "PUT", body)
        else:
            self.generic_request("/v1/policies", "POST", body)

    def delete_policy(self, id: str) -> None:
        self.generic_request(f"/v1/policies/{id}", "DELETE")

    class NotifierIdentifiers(BaseModel):
        id: str
        name: str

    def list_notifiers(self) -> list[NotifierIdentifiers]:
        return [
            self.NotifierIdentifiers(id=c["id"], name=c["name"])
            for c in self.generic_request("/v1/notifiers", "GET").json()["notifiers"]
        ]
