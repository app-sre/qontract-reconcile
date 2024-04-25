import logging
import re
import string

from gitlab.exceptions import GitlabGetError
from pydantic import BaseModel

from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.merge_request_manager.merge_request_manager import (
    MergeRequestManagerBase,
)
from reconcile.utils.merge_request_manager.parser import Parser
from reconcile.utils.mr.base import MergeRequestBase
from reconcile.utils.mr.labels import AUTO_MERGE
from reconcile.utils.vcs import VCS

AWS_MGR = "aws-account-manager"


class AwsAccountMR(MergeRequestBase):
    name = "AwsAccount"

    def __init__(
        self,
        title: str,
        description: str,
        account_tmpl_file_path: str,
        account_tmpl_file_content: str,
        account_request_file_path: str,
        labels: list[str],
    ):
        super().__init__()
        self._title = title
        self._description = description
        self._account_tmpl_file_path = account_tmpl_file_path.lstrip("/")
        self._account_tmpl_file_content = account_tmpl_file_content
        self._account_request_file_path = account_request_file_path.lstrip("/")
        self.labels = labels

    @property
    def title(self) -> str:
        return self._title

    @property
    def description(self) -> str:
        return self._description

    def process(self, gitlab_cli: GitLabApi) -> None:
        gitlab_cli.create_file(
            branch_name=self.branch,
            file_path=self._account_tmpl_file_path,
            commit_message="add account template file",
            content=self._account_tmpl_file_content,
        )
        gitlab_cli.delete_file(
            branch_name=self.branch,
            file_path=self._account_request_file_path,
            commit_message="delete account request file",
        )


DATA_SEPARATOR = (
    "**AWS Account Manager Data - DO NOT MANUALLY CHANGE ANYTHING BELOW THIS LINE**"
)
AWS_ACCOUNT_MANAGER_VERSION = "1.0.0"
AWSMR_LABEL = "template-output"

VERSION_REF = "aws_account_mgr_version"
ACCOUNT_PATH_REF = "aws_acccount_file_path"

COMPILED_REGEXES = {
    i: re.compile(rf".*{i}: (.*)$", re.MULTILINE)
    for i in [
        VERSION_REF,
        ACCOUNT_PATH_REF,
    ]
}

MR_DESC = string.Template(
    f"""
This MR is triggered by app-interface's [aws account manager](https://github.com/app-sre/qontract-reconcile/blob/master/reconcile/aws_account_manager/integration.py).

Please **do not remove the {AWSMR_LABEL} label** from this MR!

Parts of this description are used by the AWS Account Manager to manage the MR.

{DATA_SEPARATOR}

* {VERSION_REF}: $version
* {ACCOUNT_PATH_REF}: $aws_acccount_file_path
"""
)


class AwsAccountInfo(BaseModel):
    aws_acccount_file_path: str


def create_parser() -> Parser:
    return Parser[AwsAccountInfo](
        klass=AwsAccountInfo,
        compiled_regexes=COMPILED_REGEXES,
        version_ref=VERSION_REF,
        expected_version=AWS_ACCOUNT_MANAGER_VERSION,
        data_separator=DATA_SEPARATOR,
    )


def render_description(
    aws_acccount_file_path: str, version: str = AWS_ACCOUNT_MANAGER_VERSION
) -> str:
    return MR_DESC.substitute(
        aws_acccount_file_path=aws_acccount_file_path, version=version
    )


class MrData(BaseModel):
    title: str
    account_tmpl_file_path: str
    account_tmpl_file_content: str
    account_request_file_path: str


class MergeRequestManager(MergeRequestManagerBase):
    """Manager for AWS account merge requests."""

    def __init__(self, vcs: VCS, auto_merge_enabled: bool):
        super().__init__(vcs, create_parser(), AWS_MGR)
        self._auto_merge_enabled = auto_merge_enabled

    def create_merge_request(
        self,
        data: MrData,
    ) -> None:
        if not self._housekeeping_ran:
            self.housekeeping()

        """Open new MR (if not already present) for an AWS account and remove the account request file."""
        if self._merge_request_already_exists({
            ACCOUNT_PATH_REF: data.account_tmpl_file_path
        }):
            return None

        try:
            self._vcs.get_file_content_from_app_interface_master(
                file_path=data.account_tmpl_file_path
            )
            # File already exists
            raise FileExistsError(
                f"File {data.account_tmpl_file_path} already exists in the repository"
            )
        except GitlabGetError as e:
            if e.response_code != 404:
                raise e

        logging.info("Open MR for %s", data.account_tmpl_file_path)
        mr_labels = [AWS_MGR]
        if self._auto_merge_enabled:
            mr_labels.append(AUTO_MERGE)
        self._vcs.open_app_interface_merge_request(
            mr=AwsAccountMR(
                title=data.title,
                description=render_description(data.account_tmpl_file_path),
                account_tmpl_file_path=data.account_tmpl_file_path,
                account_tmpl_file_content=data.account_tmpl_file_content,
                account_request_file_path=data.account_request_file_path,
                labels=mr_labels,
            )
        )
