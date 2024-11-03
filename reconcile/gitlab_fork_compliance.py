import logging
import sys

from gitlab import GitlabGetError
from gitlab.const import MAINTAINER_ACCESS

from reconcile import queries
from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.mr.labels import BLOCKED_BOT_ACCESS
from reconcile.utils.secret_reader import create_secret_reader

LOG = logging.getLogger(__name__)

QONTRACT_INTEGRATION = "gitlab-fork-compliance"

MSG_BRANCH = (
    '@{user}, this Merge Request is using the "master" '
    "source branch. Please submit a new Merge Request from another "
    "branch."
)

MSG_ACCESS = (
    "@{user}, the user @{bot} is not a Maintainer in "
    "your fork of {project_name}. "
    "Please add the @{bot} user to your fork as a Maintainer "
    'and retest by commenting "/retest" on the Merge Request.'
)


class GitlabForkCompliance:
    OK = 0x0000
    ERR_MASTER_BRANCH = 0x0001
    ERR_NOT_A_MEMBER = 0x0002
    ERR_NOT_A_MAINTAINER = 0x0004

    def __init__(self, project_id, mr_id, maintainers_group):
        self.exit_code = self.OK

        self.maintainers_group = maintainers_group

        self.instance = queries.get_gitlab_instance()
        vault_settings = get_app_interface_vault_settings()
        self.secret_reader = create_secret_reader(use_vault=vault_settings.vault)

        self.gl_cli = GitLabApi(
            self.instance, project_id=project_id, secret_reader=self.secret_reader
        )
        self.mr = self.gl_cli.get_merge_request(mr_id)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.gl_cli.cleanup()
        if hasattr(self, "src") and self.src is not None:
            self.src.cleanup()

    def run(self):
        self.exit_code |= self.check_branch()
        self.exit_code |= self.check_bot_access()
        if self.exit_code:
            sys.exit(self.exit_code)

        # At this point, we know that the bot is a maintainer, so
        # we check if all the maintainers are in the fork, adding those
        # who are not
        if self.maintainers_group:
            group = self.gl_cli.gl.groups.get(self.maintainers_group)
            maintainers = group.members.list(iterator=True)
            project_maintainers = self.src.get_project_maintainers()
            for member in maintainers:
                if member.username in project_maintainers:
                    continue
                LOG.info([f"adding {member.username} as maintainer"])
                user_payload = {"user_id": member.id, "access_level": MAINTAINER_ACCESS}
                member = self.src.project.members.create(user_payload)
                member.save()

        # Last but not least, we remove the blocked label, in case
        # it is set
        if BLOCKED_BOT_ACCESS in self.mr.labels:
            self.gl_cli.remove_label(self.mr, BLOCKED_BOT_ACCESS)

        sys.exit(self.exit_code)

    def check_branch(self):
        # The Merge Request can use the 'master' source branch
        if self.mr.source_branch == "master":
            self.handle_error("source branch can not be master", MSG_BRANCH)
            return self.ERR_MASTER_BRANCH

        return self.OK

    def check_bot_access(self):
        try:
            self.src = GitLabApi(
                self.instance,
                project_id=self.mr.source_project_id,
                secret_reader=self.secret_reader,
            )
        except GitlabGetError:
            self.handle_error("access denied for user {bot}", MSG_ACCESS)
            return self.ERR_NOT_A_MEMBER

        if self.gl_cli.user.username not in self.src.get_project_maintainers():
            self.handle_error(
                "{bot} is not a maintainer in the fork project", MSG_ACCESS
            )
            return self.ERR_NOT_A_MAINTAINER

        return self.OK

    def handle_error(self, log_msg, mr_msg):
        LOG.error([log_msg.format(bot=self.gl_cli.user.username)])
        self.gl_cli.add_label_to_merge_request(self.mr, BLOCKED_BOT_ACCESS)
        comment = mr_msg.format(
            user=self.mr.author["username"],
            bot=self.gl_cli.user.username,
            project_name=self.gl_cli.project.name,
        )
        self.mr.notes.create({"body": comment})


def run(dry_run, project_id, mr_id, maintainers_group):
    with GitlabForkCompliance(project_id, mr_id, maintainers_group) as gfc:
        gfc.run()
