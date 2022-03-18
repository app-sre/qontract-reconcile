from datetime import datetime
from pathlib import Path

from jinja2 import Template
from ruamel.yaml.scalarstring import PreservedScalarString as pss

from reconcile.utils.mr.base import MergeRequestBase
from reconcile.utils.mr.labels import AUTO_MERGE
from reconcile.utils.constants import PROJ_ROOT

EMAIL_TEMPLATE = PROJ_ROOT / "templates" / "email.yml.j2"


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
    def title(self):
        return f"[{self.name}] reports for {self.isodate}"

    def process(self, gitlab_cli):
        actions = [
            {
                "action": "create",
                "file_path": report["file_path"],
                "content": report["content"],
            }
            for report in self.reports
        ]
        gitlab_cli.create_commit(self.branch, self.title, actions)

        with open(EMAIL_TEMPLATE) as file_obj:
            template = Template(
                file_obj.read(), keep_trailing_newline=True, trim_blocks=True
            )

        content = template.render(
            NAME=f"app-interface-reporter-{self.ts}",
            SUBJECT=self.title,
            ALIASES=["all-service-owners"],
            BODY=pss(self.email_body),
        )

        email_path = Path("data") / "app-interface" / "emails" / f"{self.ts}.yml"

        gitlab_cli.create_file(
            branch_name=self.branch,
            file_path=str(email_path),
            commit_message=self.title,
            content=content,
        )
