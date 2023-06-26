from pathlib import Path

from jinja2 import Template
from ruamel import yaml
from ruamel.yaml.scalarstring import PreservedScalarString as pss

from reconcile.utils.constants import PROJ_ROOT
from reconcile.utils.mr.base import (
    MergeRequestBase,
    app_interface_email,
)
from reconcile.utils.mr.labels import AUTO_MERGE

BODY_TEMPLATE = PROJ_ROOT / "templates" / "aws_access_key_email.j2"


class CreateDeleteAwsAccessKey(MergeRequestBase):
    name = "create_delete_aws_access_key_mr"

    def __init__(self, account, path, key):
        self.account = account
        self.path = path.lstrip("/")
        self.key = key

        super().__init__()

        self.labels = [AUTO_MERGE]

    @property
    def title(self) -> str:
        return f"[{self.name}] delete {self.account} access key {self.key}"

    @property
    def description(self) -> str:
        return f"delete {self.account} access key {self.key}"

    def process(self, gitlab_cli):
        # add key to deleteKeys list to be picked up by aws-iam-keys
        raw_file = gitlab_cli.project.files.get(
            file_path=self.path, ref=self.main_branch
        )
        content = yaml.load(raw_file.decode(), Loader=yaml.RoundTripLoader)

        content.setdefault("deleteKeys", [])
        content["deleteKeys"].append(self.key)

        new_content = "---\n"
        new_content += yaml.dump(content, Dumper=yaml.RoundTripDumper)

        msg = "Add key to deleteKeys list to be picked up by aws-iam-keys"
        gitlab_cli.update_file(
            branch_name=self.branch,
            file_path=self.path,
            commit_message=msg,
            content=new_content,
        )

        # add a new email to be picked up by email-sender
        with open(BODY_TEMPLATE) as file_obj:
            body_template = Template(
                file_obj.read(), keep_trailing_newline=True, trim_blocks=True
            )

        body = body_template.render(ACCOUNT=self.account, ACCESS_KEY=self.key)
        email_name = f"{self.account}-{self.key}"
        ref = self.path[4:] if self.path.startswith("data") else self.path
        content = app_interface_email(
            name=email_name, subject=self.title, aws_accounts=[ref], body=pss(body)
        )

        email_path = Path("data") / "app-interface" / "emails" / f"{email_name}.yml"
        gitlab_cli.create_file(
            branch_name=self.branch,
            file_path=str(email_path),
            commit_message=self.title,
            content=content,
        )
