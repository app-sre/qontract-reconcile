from typing import Any, Optional

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
    def _build_policy(
        self, api_policy: Any, conditions: list[PolicyCondition]
    ) -> Policy:
        return Policy(
            name=api_policy["name"],
            description=api_policy["description"],
            notifiers=sorted(api_policy["notifiers"]),
            categories=sorted(api_policy["categories"]),
            severity=api_policy["severity"],
            scope=sorted(
                [
                    Scope(
                        cluster=s["cluster"],
                        namespace=s["namespace"],
                    )
                    for s in api_policy["scope"]
                ],
                key=lambda s: s.cluster,
            ),
            conditions=conditions,
        )

    def _build_policy_condition(self, api_policy_group: Any) -> PolicyCondition:
        return PolicyCondition(
            field_name=api_policy_group["fieldName"],
            values=[v["value"] for v in api_policy_group["values"]],
            negate=api_policy_group["negate"],
        )

    def list_custom_policies(self) -> list[Any]:
        # retrieve summary data for each custom policy
        return [
            p
            for p in self.generic_request("/v1/policies", "GET").json()["policies"]
            if not p["isDefault"]
        ]

    def get_custom_policies(self) -> list[Policy]:
        custom_policy_ids = [p["id"] for p in self.list_custom_policies()]
        # make individual policy requests to obtain further details
        custom_policies_api_result = [
            self.generic_request(f"/v1/policies/{pid}", "GET").json()
            for pid in custom_policy_ids
        ]
        return [
            self._build_policy(
                api_policy=cp,
                conditions=[
                    self._build_policy_condition(group)
                    for section in cp["policySections"]
                    for group in section.get("policyGroups", [])
                ],
            )
            for cp in custom_policies_api_result
        ]

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
