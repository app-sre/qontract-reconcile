from datetime import datetime
from pathlib import Path

from jinja2 import Template

from reconcile.utils.constants import PROJ_ROOT
from reconcile.utils.mr.base import MergeRequestBase
from reconcile.utils.mr.labels import DO_NOT_MERGE_HOLD

EMAIL_TEMPLATE = PROJ_ROOT / "templates" / "email.yml.j2"


class CreateAppInterfaceNotificator(MergeRequestBase):

    name = "create_app_interface_notificator_mr"

    def __init__(self, notification):
        """
        :param notification: the notification data. Example:

        {
            "notification_type": "Outage",
            "description": "The AppSRE team is current investigating ...",
            "short_description": "Outage notification",
            "recipients": [
                "/teams/app-sre/users/asegundo.yml"
            ]
        }

        :type notification: dict
        """
        self.notification = notification

        super().__init__()

        self.labels = [DO_NOT_MERGE_HOLD]

    @property
    def title(self) -> str:
        return (
            f"[{self.name}] "
            f"{self.notification['notification_type']}: "
            f"{self.notification['short_description']}"
        )

    @property
    def description(self) -> str:
        return (
            f"{self.notification['notification_type']}: "
            f"{self.notification['short_description']}"
        )

    def process(self, gitlab_cli):
        now = datetime.now()
        ts = now.strftime("%Y%m%d%H%M%S")
        short_date = now.strftime("%Y-%m-%d")

        with open(EMAIL_TEMPLATE) as file_obj:
            template = Template(
                file_obj.read(), keep_trailing_newline=True, trim_blocks=True
            )

        subject = (
            f'[{self.notification["notification_type"]}] '
            f'{self.notification["short_description"]} - '
            f"{short_date}"
        )

        content = template.render(
            NAME=f"{self.name}-{ts}",
            SUBJECT=subject,
            USERS=self.notification["recipients"],
            BODY=self.notification["description"],
        )

        email_path = Path("data") / "app-interface" / "emails" / f"{ts}.yml"
        commit_message = f"[{self.name}] adding notification"
        gitlab_cli.create_file(
            branch_name=self.branch,
            file_path=str(email_path),
            commit_message=commit_message,
            content=content,
        )
