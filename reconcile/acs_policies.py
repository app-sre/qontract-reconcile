import logging
from collections.abc import Callable

from reconcile.gql_definitions.acs.acs_policies import query as acs_policies_query
from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.utils import gql
from reconcile.utils.acs.policies import AcsPolicyApi, Policy, PolicyCondition, Scope
from reconcile.utils.differ import diff_iterables, DiffPair

from reconcile.utils.runtime.integration import (
    NoParams,
    QontractReconcileIntegration,
)
from reconcile.utils.secret_reader import create_secret_reader
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

    def get_desired_state(self, query_func: Callable) -> list[Policy]:
        """
        Get desired ACS security policies and convert to acs api policy object format

        :param query_func: function which queries GQL server
        :return: list of utils.acs.policies.Policy derived from acs-policy-1 definitions
        """

        policies = []
        for gql_policy in acs_policies_query(query_func=query_func).acs_policies:
            conditions: list[PolicyCondition] = []
            for c in gql_policy.conditions:
                pc = PolicyCondition(
                    field_name=POLICY_CONDITION_FIELD_NAMES[c.policy_field],
                    negate=False,
                    values=[],
                )
                if c.policy_field == "cvss":
                    pc.values = [
                        f"{POLICY_CONDITION_COMPARISONS[c.comparison]}{c.score}"
                    ]
                elif c.policy_field == "severity":
                    pc.values = [
                        f"{POLICY_CONDITION_COMPARISONS[c.comparison]}{c.level.upper()}"
                    ]
                elif c.policy_field == "cve":
                    pc.values = [str(c.fixable).lower()]
                elif c.policy_field == "image_tag":
                    pc.values = c.tags
                    pc.negate = c.negate
                elif c.policy_field == "image_age":
                    pc.values = [str(c.days)]
                else:
                    logging.warning(
                        "unsupported policyField encountered: %s", c.policy_field
                    )
                    continue
                conditions.append(pc)

            policies.append(
                Policy(
                    name=gql_policy.name,
                    description=gql_policy.description,
                    severity=f"{gql_policy.severity.upper()}_SEVERITY",  # align with acs api severity value format
                    scope=sorted(
                        [
                            Scope(cluster=cs.name, namespace="")
                            for cs in gql_policy.scope.clusters
                        ],
                        key=lambda s: s.cluster,
                    )
                    if gql_policy.scope.level == "cluster"
                    else [
                        Scope(cluster=ns.cluster.name, namespace=ns.name)
                        for ns in gql_policy.scope.namespaces
                    ],
                    categories=sorted([
                        POLICY_CATEGORIES[pc] for pc in gql_policy.categories
                    ]),
                    conditions=conditions,
                )
            )
        return policies

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
            if not dry_run:
                try:
                    acs.create_policy(a)
                except Exception as e:
                    errors.append(e)
            logging.info("Created policy: %s", a.name)
        if len(diff.delete) > 0 or len(diff.change) > 0:
            policy_id_names = acs.get_custom_policy_id_names()
            for d in diff.delete.values():
                if not dry_run:
                    try:
                        acs.delete_policy(policy_id_names[d.name])
                    except Exception as e:
                        errors.append(e)
                logging.info("Deleted policy: %s", d.name)
            for c in diff.change.values():
                if not dry_run:
                    try:
                        acs.update_policy(policy_id_names[c.current.name], c.desired)
                    except Exception as e:
                        errors.append(e)
                logging.info("Updated policy: %s", c.desired.name)
        if errors:
            raise ExceptionGroup("Reconcile errors occurred", errors)

    def run(
        self,
        dry_run: bool,
    ) -> None:
        gqlapi = gql.get_api()
        instance = AcsPolicyApi.get_acs_instance(gqlapi.query)

        vault_settings = get_app_interface_vault_settings()
        secret_reader = create_secret_reader(use_vault=vault_settings.vault)
        token = secret_reader.read_all_secret(instance.credentials)

        desired = self.get_desired_state(gqlapi.query)

        with AcsPolicyApi(
            instance={"url": instance.url, "token": token[instance.credentials.field]}
        ) as acs_api:
            current = acs_api.get_custom_policies()
            self.reconcile(
                desired=desired, current=current, acs=acs_api, dry_run=dry_run
            )