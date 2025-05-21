import logging
from collections.abc import Callable
from typing import cast

import reconcile.gql_definitions.acs.acs_policies as gql_acs_policies
from reconcile.gql_definitions.acs.acs_policies import (
    AcsPolicyConditionsV1,
    AcsPolicyV1,
)
from reconcile.utils import gql
from reconcile.utils.acs.policies import AcsPolicyApi, Policy, PolicyCondition, Scope
from reconcile.utils.differ import diff_iterables
from reconcile.utils.runtime.integration import (
    NoParams,
    QontractReconcileIntegration,
)
from reconcile.utils.semver_helper import make_semver

# proceeding constants map schema enum values to corresponding acs api defaults
POLICY_CATEGORIES = {
    "anomalous-activity": "Anomalous Activity",
    "devops-best-practices": "DevOps Best Practices",
    "kubernetes": "Kubernetes",
    "privileges": "Privileges",
    "security-best-practices": "Security Best Practices",
    "vulnerability-management": "Vulnerability Management",
}

POLICY_CONDITION_COMPARISONS = {
    "gt": ">",
    "gte": ">=",
    "eq": "",
    "lt": "<",
    "lte": "<=",
}

POLICY_CONDITION_FIELD_NAMES = {
    "cvss": "CVSS",
    "severity": "Severity",
    "imageTag": "Image Tag",
    "imageAge": "Image Age",
    "cve": "Fixable",
}


class AcsPoliciesIntegration(QontractReconcileIntegration[NoParams]):
    def __init__(self) -> None:
        super().__init__(NoParams())
        self.qontract_integration = "acs_policies"
        self.qontract_integration_version = make_semver(0, 1, 0)

    @property
    def name(self) -> str:
        return self.qontract_integration.replace("_", "-")

    def _build_policy(
        self,
        gql_policy: AcsPolicyV1,
        notifier_name_to_id: dict[str, str],
        cluster_name_to_id: dict[str, str],
    ) -> Policy:
        conditions = [
            pc for c in gql_policy.conditions if (pc := self._build_policy_condition(c))
        ]
        return Policy(
            name=gql_policy.name,
            description=gql_policy.description,
            notifiers=[],
            severity=f"{gql_policy.severity.upper()}_SEVERITY",  # align with acs api severity value format
            scope=sorted(
                [
                    Scope(cluster=cluster_name_to_id[cs.name], namespace="")
                    for cs in cast(
                        gql_acs_policies.AcsPolicyScopeClusterV1,
                        gql_policy.scope,
                    ).clusters
                ],
                key=lambda s: s.cluster,
            )
            if gql_policy.scope.level == "cluster"
            else sorted(
                [
                    Scope(
                        cluster=cluster_name_to_id[ns.cluster.name], namespace=ns.name
                    )
                    for ns in cast(
                        gql_acs_policies.AcsPolicyScopeNamespaceV1,
                        gql_policy.scope,
                    ).namespaces
                ],
                key=lambda s: s.cluster,
            ),
            categories=sorted([POLICY_CATEGORIES[pc] for pc in gql_policy.categories]),
            conditions=conditions,
        )

    def _build_policy_condition(
        self, condition: AcsPolicyConditionsV1
    ) -> PolicyCondition | None:
        field_name = POLICY_CONDITION_FIELD_NAMES[condition.policy_field]
        match condition.policy_field:
            case "cvss":
                cvss_condition = cast(
                    gql_acs_policies.AcsPolicyConditionsCvssV1, condition
                )
                return PolicyCondition(
                    field_name=field_name,
                    negate=False,
                    values=[
                        f"{POLICY_CONDITION_COMPARISONS[cvss_condition.comparison]}{cvss_condition.score}"
                    ],
                )
            case "severity":
                severity_condition = cast(
                    gql_acs_policies.AcsPolicyConditionsSeverityV1, condition
                )
                return PolicyCondition(
                    field_name=field_name,
                    negate=False,
                    values=[
                        f"{POLICY_CONDITION_COMPARISONS[severity_condition.comparison]}{severity_condition.level.upper()}"
                    ],
                )
            case "cve":
                cve_condition = cast(
                    gql_acs_policies.AcsPolicyConditionsCveV1, condition
                )
                return PolicyCondition(
                    field_name=field_name,
                    negate=False,
                    values=[str(cve_condition.fixable).lower()],
                )
            case "image_tag":
                image_tag_condition = cast(
                    gql_acs_policies.AcsPolicyConditionsImageTagV1, condition
                )
                return PolicyCondition(
                    field_name=field_name,
                    # negate utilized to enforce policy in which image tag should not be any
                    # defined in list of values
                    negate=image_tag_condition.negate or False,
                    values=image_tag_condition.tags,
                )
            case "image_age":
                image_age_condition = cast(
                    gql_acs_policies.AcsPolicyConditionsImageAgeV1, condition
                )
                return PolicyCondition(
                    field_name=field_name,
                    negate=False,
                    values=[str(image_age_condition.days)],
                )
            case _:
                logging.warning(
                    "unsupported policyField encountered: %s", condition.policy_field
                )
                return None

    def get_desired_state(
        self,
        query_func: Callable,
        notifiers: list[AcsPolicyApi.NotifierIdentifiers],
        clusters: list[AcsPolicyApi.ClusterIdentifiers],
    ) -> list[Policy]:
        """
        Get desired ACS security policies and convert to acs api policy object format

        :param query_func: function which queries GQL server
        :return: list of utils.acs.policies.Policy derived from acs-policy-1 definitions
        """
        notifier_name_to_id = {n.name: n.id for n in notifiers}
        cluster_name_to_id = {c.name: c.id for c in clusters}
        return [
            self._build_policy(gql_policy, notifier_name_to_id, cluster_name_to_id)
            for gql_policy in gql_acs_policies.query(query_func=query_func).acs_policies
            or []
        ]

    def reconcile(
        self,
        desired: list[Policy],
        current: list[Policy],
        acs: AcsPolicyApi,
        dry_run: bool,
    ) -> None:
        errors = []
        diff = diff_iterables(current=current, desired=desired, key=lambda x: x.name)
        for a in diff.add.values():
            logging.info("Create policy: %s", a.name)
            if not dry_run:
                try:
                    acs.create_or_update_policy(desired=a)
                except Exception as e:
                    errors.append(e)
        if diff.delete or diff.change:
            policy_id_by_name = {p["name"]: p["id"] for p in acs.list_custom_policies()}
            for d in diff.delete.values():
                logging.info("Delete policy: %s", d.name)
                if not dry_run:
                    try:
                        acs.delete_policy(policy_id_by_name[d.name])
                    except Exception as e:
                        errors.append(e)
            for c in diff.change.values():
                logging.info("Update policy: %s", c.desired.name)
                if not dry_run:
                    try:
                        acs.create_or_update_policy(
                            desired=c.desired, id=policy_id_by_name[c.current.name]
                        )
                    except Exception as e:
                        errors.append(e)
        if errors:
            raise ExceptionGroup("Reconcile errors occurred", errors)

    def run(
        self,
        dry_run: bool,
    ) -> None:
        gqlapi = gql.get_api()
        instance = AcsPolicyApi.get_acs_instance(gqlapi.query)
        with AcsPolicyApi(
            url=instance.url, token=self.secret_reader.read_secret(instance.credentials)
        ) as acs_api:
            notifiers = acs_api.list_notifiers()
            clusters = acs_api.list_clusters()
            desired = self.get_desired_state(gqlapi.query, notifiers, clusters)
            current = acs_api.get_custom_policies()
            self.reconcile(
                desired=desired, current=current, acs=acs_api, dry_run=dry_run
            )
