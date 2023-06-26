import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.mr.base import (
    MergeRequestBase,
    app_interface_email,
)
from reconcile.utils.mr.labels import DO_NOT_MERGE_HOLD


class Notification(BaseModel):
    # type of notification. E.g. Outage, Maintenance, etc.
    notification_type: str
    # short description of the notification.
    short_description: str
    # long description of the notification.
    description: str
    # list of recipients (user references). E.g. ['/teams/app-sre/users/chuck-norris.yml', ...]
    recipients: list[str]
    # list of services (app references). E.g. ['/services/app-interface/app.yml', ...]
    services: list[str]


class CreateAppInterfaceNotificator(MergeRequestBase):
    name = "create_app_interface_notificator_mr"

    def __init__(
        self,
        notification: Notification,
        labels: Optional[list[str]] = None,
        email_base_path: Path = Path("data") / "app-interface" / "emails",
        dry_run: bool = False,
    ):
        self._notification_as_dict = notification.dict()
        super().__init__()
        self._notification = notification
        self._email_base_path = email_base_path
        self._dry_run = dry_run
        self.labels = labels if labels else [DO_NOT_MERGE_HOLD]

    @property
    def title(self) -> str:
        return (
            f"[{self.name}] "
            f"{self._notification.notification_type}: "
            f"{self._notification.short_description}"
        )

    @property
    def description(self) -> str:
        return (
            f"{self._notification.notification_type}: "
            f"{self._notification.short_description}"
        )

    def process(self, gitlab_cli: GitLabApi) -> None:
        now = datetime.now()
        ts = now.strftime("%Y%m%d%H%M%S")
        short_date = now.strftime("%Y-%m-%d")

        subject = (
            f"[{self._notification.notification_type}] "
            f"{self._notification.short_description} - "
            f"{short_date}"
        )

        content = app_interface_email(
            name=f"{self.name}-{ts}",
            subject=subject,
            body=self._notification.description,
            users=self._notification.recipients,
            apps=self._notification.services,
        )

        email_path = self._email_base_path / f"{ts}.yml"
        commit_message = f"[{self.name}] adding notification"
        if not self._dry_run:
            logging.info(f"no-dry-run: creating gitlab file: {email_path}")
            gitlab_cli.create_file(
                branch_name=self.branch,
                file_path=str(email_path),
                commit_message=commit_message,
                content=content,
            )
        else:
            logging.info(f"dry-run: skipping gitlab file creation: {email_path}")
            logging.info(f"email: {content}")
