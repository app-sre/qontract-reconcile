from collections.abc import Callable

from qontract_utils.secret_reader import SecretBackend

from qontract_api.cache import CacheBackend
from qontract_api.config import Settings
from qontract_api.external.pagerduty.pagerduty_workspace_client import (
    PagerDutyWorkspaceClient,
)
from qontract_api.integrations.slack_usergroups_v2.models import SlackUsergroupsUser


class UserSourcePagerDutyResolver:
    def __init__(
        self,
        users: list[SlackUsergroupsUser],
        cache: CacheBackend,
        secret_reader: SecretBackend,
        settings: Settings,
        pagerduty_workspace_client_builder: Callable[..., PagerDutyWorkspaceClient],
    ):
        self.pagerduty_workspace_client_builder = pagerduty_workspace_client_builder
        self.cache = cache
        self.secret_reader = secret_reader
        self.settings = settings
        self.org_usernames = {user.org_username for user in users}

    def resolve(
        self,
        instance_name: str,
        schedule_id: str | None,
        escalation_policy_id: str | None,
    ) -> set[str]:
        if not schedule_id and not escalation_policy_id:
            return set()

        # TODO: reuse client and cleanup
        client = self.pagerduty_workspace_client_builder(
            instance_name=instance_name,
            cache=self.cache,
            secret_reader=self.secret_reader,
            settings=self.settings,
        )

        schedule_users = client.get_schedule_users(schedule_id) if schedule_id else []
        escalation_policy_users = (
            client.get_escalation_policy_users(escalation_policy_id)
            if escalation_policy_id
            else []
        )
        return {
            user.org_username
            for user in schedule_users + escalation_policy_users
            if (user.org_username in self.org_usernames)
        }
