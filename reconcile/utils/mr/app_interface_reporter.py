from datetime import datetime
from pathlib import Path

from ruamel.yaml.scalarstring import PreservedScalarString as pss

from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.mr.base import (
    MergeRequestBase,
    app_interface_email,
)
from reconcile.utils.mr.labels import AUTO_MERGE


class CreateAppInterfaceReporter(MergeRequestBase):
    name = "create_app_interface_reporter_mr"

    def __init__(self, reports, email_body, reports_path):
        self.reports = reports
        self.email_body = email_body
        self.reports_path = reports_path

        super().__init__()

        self.labels = [AUTO_MERGE]

        now = datetime.now()
        self.isodate = now.isoformat()
        self.ts = now.strftime("%Y%m%d%H%M%S")

    @property
    def title(self) -> str:
        return f"[{self.name}] reports for {self.isodate}"

    @property
    def description(self) -> str:
        return f"reports for {self.isodate}"

    def process(self, gitlab_cli: GitLabApi) -> None:
        actions = [
            {
                "action": "create",
                "file_path": report["file_path"],
                "content": report["content"],
            }
            for report in self.reports
        ]
        gitlab_cli.create_commit(self.branch, self.title, actions)

        content = app_interface_email(
            name=f"app-interface-reporter-{self.ts}",
            subject=self.title,
            aliases=["all-service-owners"],
            body=pss(self.email_body),
        )

        email_path = Path("data") / "app-interface" / "emails" / f"{self.ts}.yml"

        gitlab_cli.create_file(
            branch_name=self.branch,
            file_path=str(email_path),
            commit_message=self.title,
            content=content,
        )
