from __future__ import annotations

from collections.abc import (
    Callable,
    Iterable,
)
from functools import lru_cache

from reconcile.gql_definitions.common.ocm_environments import (
    query as ocm_environment_query,
)
from reconcile.gql_definitions.fragments.ocm_environment import OCMEnvironment
from reconcile.slack_base import slackapi_from_queries
from reconcile.utils import gql
from reconcile.utils.ocm_base_client import (
    OCMAPIClientConfigurationProtocol,
    OCMBaseClient,
    init_ocm_base_client,
)
from reconcile.utils.runtime.integration import (
    NoParams,
    QontractReconcileIntegration,
)
from reconcile.utils.secret_reader import SecretReaderBase

QONTRACT_INTEGRATION = "ocm-internal-notifications"


class OcmInternalNotifications(QontractReconcileIntegration[NoParams]):
    """Something."""

    def __init__(self) -> None:
        super().__init__(NoParams())
        self.slack = slackapi_from_queries(
            integration_name=self.name, init_usergroups=False
        )

    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    def get_environments(self, query_func: Callable) -> list[OCMEnvironment]:
        return ocm_environment_query(query_func).environments

    def init_ocm_apis(
        self,
        environments: Iterable[OCMEnvironment],
        init_ocm_base_client: Callable[
            [OCMAPIClientConfigurationProtocol, SecretReaderBase], OCMBaseClient
        ] = init_ocm_base_client,
    ) -> dict[str, OCMBaseClient]:
        return {
            env.name: init_ocm_base_client(env, self.secret_reader)
            for env in environments
        }

    @lru_cache
    def slack_get_user_id_by_name(self, user_name: str, mail_address: str) -> str:
        return self.slack.get_user_id_by_name(
            user_name=user_name, mail_address=mail_address
        )

    def run(self, dry_run: bool) -> None:
        gqlapi = gql.get_api()
        environments = self.get_environments(gqlapi.query)

        self.ocm_apis = self.init_ocm_apis(environments, init_ocm_base_client)

        for env_name, ocm in self.ocm_apis.items():
            if env_name == "ocm-production":
                continue

            clusters = ocm.get(
                api_path="/api/clusters_mgmt/v1/clusters",
                params={"search": "state like 'uninstalling' and managed='true'"},
            ).get("items")

            slack_user_ids = set()
            for cluster in clusters:
                subscription = ocm.get(api_path=cluster["subscription"]["href"])
                creator = ocm.get(api_path=subscription["creator"]["href"])
                email = creator["email"]
                user, mail_address = email.split("@")
                user_name = user.split("+")[0]
                slack_user_ids.add(
                    self.slack_get_user_id_by_name(user_name, mail_address)
                )

            if not dry_run:
                users = " ".join([f"<@{uid}>" for uid in slack_user_ids])
                self.slack.chat_post_message(
                    f"hey {users} :wave: you have clusters stuck in uninstalling state in the {env_name} environment"
                )
