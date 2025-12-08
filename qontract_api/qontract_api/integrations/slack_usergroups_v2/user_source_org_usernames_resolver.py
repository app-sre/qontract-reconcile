from qontract_api.integrations.slack_usergroups_v2.models import SlackUsergroupsUser


class UserSourceOrgUsernamesResolver:
    def __init__(self, users: list[SlackUsergroupsUser]):
        self.org_usernames = {user.org_username for user in users}

    def resolve(self, org_usernames: list[str]) -> set[str]:
        return {
            org_username
            for org_username in org_usernames
            if org_username in self.org_usernames
        }
