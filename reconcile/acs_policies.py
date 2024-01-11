from collections.abc import Callable

from reconcile.gql_definitions.acs.acs_policies import AcsPolicyV1
from reconcile.gql_definitions.acs.acs_policies import query as acs_policies_query
from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.utils import gql
from reconcile.utils.acs.policies import AcsPolicyApi, Policy
from reconcile.utils.differ import diff_iterables

from reconcile.utils.runtime.integration import (
    NoParams,
    QontractReconcileIntegration,
)
from reconcile.utils.secret_reader import create_secret_reader
from reconcile.utils.semver_helper import make_semver


class AcsPoliciesIntegration(QontractReconcileIntegration[NoParams]):
    def __init__(self) -> None:
        super().__init__(NoParams())
        self.qontract_integration = "acs_policies"
        self.qontract_integration_version = make_semver(0, 1, 0)

    @property
    def name(self) -> str:
        return self.qontract_integration.replace("_", "-")

    def get_desired_state(self, query_func: Callable) -> list[AcsPolicyV1]:
        """
        Get desired ACS security policies

        :param query_func: function which queries GQL server
        :return: list of AcsPolicy derived from acs-policy-1 schema definitions
        """

        query_results = acs_policies_query(query_func=query_func).acs_policies
        if query_results is None:
            return []
        print(query_results)
        return query_results

    def reconcile(self, desired: list[Policy], current: list[Policy]):
        diff = diff_iterables(current, desired, lambda x: x.name)
        print(diff)

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
