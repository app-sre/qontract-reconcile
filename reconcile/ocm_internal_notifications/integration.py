from __future__ import annotations

import logging
from collections.abc import (
    Callable,
)
from functools import lru_cache

from reconcile.gql_definitions.common.ocm_environments import (
    query as ocm_environment_query,
)
from reconcile.gql_definitions.fragments.ocm_environment import OCMEnvironment
from reconcile.slack_base import slackapi_from_queries
from reconcile.typed_queries.app_interface_custom_messages import (
    get_app_interface_custom_message,
)
from reconcile.utils import gql
from reconcile.utils.ocm.search_filters import Filter
from reconcile.utils.ocm_base_client import (
    init_ocm_base_client,
)
from reconcile.utils.runtime.integration import (
    NoParams,
    QontractReconcileIntegration,
)
from reconcile.utils.slack_api import UserNotFoundException

QONTRACT_INTEGRATION = "ocm-internal-notifications"


class OcmInternalNotifications(QontractReconcileIntegration[NoParams]):
    """Notifications to internal Red Hat users based on conditions in OCM."""

    def __init__(self) -> None:
        super().__init__(NoParams())
        self.slack = slackapi_from_queries(
            integration_name=self.name, init_usergroups=False
        )
        self.slack_get_user_id_by_name = lru_cache()(self._slack_get_user_id_by_name)

    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    def get_environments(self, query_func: Callable) -> list[OCMEnvironment]:
        return ocm_environment_query(query_func).environments

    def _slack_get_user_id_by_name(
        self, user_name: str, mail_address: str
    ) -> str | None:
        try:
            return self.slack.get_user_id_by_name(
                user_name=user_name, mail_address=mail_address
            )
        except UserNotFoundException:
            return None

    def run(self, dry_run: bool) -> None:
        gqlapi = gql.get_api()
        environments = self.get_environments(gqlapi.query)

        for env in environments:
            ocm = init_ocm_base_client(env, self.secret_reader)

            if not (env.labels and env.labels.get("internal_notifications")):
                logging.info(
                    f"skipping environment {env.name} due to no internal_notifications label"
                )
                continue

            clusters = ocm.get(
                api_path="/api/clusters_mgmt/v1/clusters",
                params={
                    "search": Filter()
                    .eq("state", "uninstalling")
                    .eq("managed", "true")
                    .render(),
                    "orderBy": "created_at",
                },
            ).get("items")
            subscriptions = ocm.get(
                api_path="/api/accounts_mgmt/v1/subscriptions",
                params={
                    "search": Filter()
                    .is_in("id", [c["subscription"]["id"] for c in clusters])
                    .render(),
                    "orderBy": "created_at",
                },
            ).get("items")

            slack_user_ids = set()
            for subscription in subscriptions:
                creator = ocm.get(api_path=subscription["creator"]["href"])
                email = creator["email"]
                logging.info(
                    f"found managed cluster in uninstalling state in environment {env.name} with creator {email}"
                )
                user, mail_address = email.split("@")
                user_name = user.split("+")[0]
                slack_user_id = self.slack_get_user_id_by_name(user_name, mail_address)
                if slack_user_id:
                    logging.info(
                        f"found slack user id {slack_user_id} for user {user_name}"
                    )
                    slack_user_ids.add(slack_user_id)
                else:
                    logging.warning(f"slack user id not found for user {user_name}")

            if not dry_run and slack_user_ids:
                users = " ".join([f"<@{uid}>" for uid in slack_user_ids])
                instructions = (
                    get_app_interface_custom_message(
                        "ocm-internal-notifications-instructions"
                    )
                    or ""
                )
                self.slack.chat_post_message(
                    f"hey {users} :wave: you have clusters stuck in uninstalling state in the {env.name} environment. {instructions}"
                )
