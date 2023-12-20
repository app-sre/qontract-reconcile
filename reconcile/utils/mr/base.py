import json
import logging
from abc import (
    ABC,
    abstractmethod,
)
from typing import (
    Any,
    Optional,
    Union,
)
from uuid import uuid4

from gitlab.exceptions import GitlabError
from jinja2 import Template

from reconcile.utils.constants import PROJ_ROOT
from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.mr.labels import DO_NOT_MERGE_HOLD
from reconcile.utils.sqs_gateway import SQSGateway

EMAIL_TEMPLATE = PROJ_ROOT / "templates" / "email.yml.j2"

LOG = logging.getLogger(__name__)


class CancelMergeRequest(Exception):
    """
    Used when the Merge Request processing is canceled.
    """


class MergeRequestProcessingError(Exception):
    """
    Used when the merge request could not be processed for technical reasons
    """


MRClient = Union[GitLabApi, SQSGateway]


class MergeRequestBase(ABC):
    """
    Base abstract class for all merge request types.
    """

    name = "merge-request-base"

    def __init__(self):
        # Let's first get all the attributes from the instance
        # and use for the SQS Msg payload. With that, the msg
        # to the SQS is enough to create a new, similar, instance
        # of the child class.
        self.sqs_msg_data = {**self.__dict__}

        self.labels = [DO_NOT_MERGE_HOLD]

        random_id = str(uuid4())[:6]
        self.branch = f"{self.name}-{random_id}"
        self.branch_created = False

        self.remove_source_branch = True

        self.cancelled = False

    def cancel(self, message: str) -> None:
        self.cancelled = True
        raise CancelMergeRequest(
            f"{self.name} MR canceled for "
            f"branch {self.branch}. "
            f"Reason: {message}"
        )

    @property
    @abstractmethod
    def title(self) -> str:
        """
        Title of the Merge Request.

        :return: Merge Request title as seen in the Gitlab Web UI
        :rtype: str
        """

    @property
    @abstractmethod
    def description(self) -> str:
        """
        Description of the Merge Request.

        :return: Merge Request description as seen in the Gitlab Web UI
        :rtype: str
        """

    @abstractmethod
    def process(self, gitlab_cli: GitLabApi) -> None:
        """
        Called by `submit_to_gitlab`, this method is the place for
        user-defined steps to create the commits of a merge request.

        :param gitlab_cli:
        :type gitlab_cli: GitLabApi
        """

    @property
    def sqs_data(self) -> dict[str, Any]:
        """
        The SQS Message payload (MessageBody) generated out of
        the Merge Request class instance.
        """
        return {
            "pr_type": self.name,
            **self.sqs_msg_data,
        }

    def submit_to_sqs(self, sqs_cli: SQSGateway) -> None:
        """
        Sends the MR message to SQS.

        :param sqs_cli: The SQS Client instance.
        :type sqs_cli: SQSGateway
        """
        sqs_cli.send_message(self.sqs_data)

    def gitlab_data(self, target_branch: str) -> dict[str, Any]:
        """
        The Gitlab payload for creating the Merge Request.
        """
        return {
            "source_branch": self.branch,
            "target_branch": target_branch,
            "title": self.title,
            "description": self.description,
            "remove_source_branch": self.remove_source_branch,
            "labels": self.labels,
        }

    def submit_to_gitlab(self, gitlab_cli: GitLabApi) -> Any:
        """
        Sends the MR to Gitlab.

        :param gitlab_cli: The SQS Client instance.
        :type gitlab_cli: GitLabApi

        :raises:
            MergeRequestProcessingError: Raised when it was not possible
              to open a MR
        """

        try:
            # Avoiding duplicate MRs
            if gitlab_cli.mr_exists(title=self.title):
                self.cancel(
                    f"MR with the same name '{self.title}' "
                    f"already exists. Aborting MR creation."
                )

            self.ensure_tmp_branch_exists(gitlab_cli)

            self.process(gitlab_cli=gitlab_cli)

            # Avoiding empty MRs
            if not self.diffs(gitlab_cli):
                self.cancel(
                    f"No changes when compared to {gitlab_cli.main_branch}. "
                    "Aborting MR creation."
                )

            return gitlab_cli.project.mergerequests.create(
                self.gitlab_data(target_branch=gitlab_cli.main_branch)
            )
        except CancelMergeRequest as mr_cancel:
            # cancellation is a valid behaviour. it indicates, that the
            # operation is not required, therefore we will not signal
            # a problem back to the caller
            self.delete_tmp_branch(gitlab_cli)
            LOG.info(mr_cancel)
        except Exception as err:
            self.delete_tmp_branch(gitlab_cli)
            # NOTE
            # sqs_msg_data might some day include confidential data and
            # we will need to revisit implications that will come from
            # logging this exception
            raise MergeRequestProcessingError(
                f"error processing {self.name} changes "
                f"{json.dumps(self.sqs_msg_data)} "
                f"into temporary branch {self.branch}. "
                f"Reason: {err}"
            ) from err

    def ensure_tmp_branch_exists(self, gitlab_cli: GitLabApi) -> None:
        if not self.branch_created:
            gitlab_cli.create_branch(
                new_branch=self.branch, source_branch=gitlab_cli.main_branch
            )
            self.branch_created = True

    def delete_tmp_branch(self, gitlab_cli: GitLabApi) -> None:
        if self.branch_created:
            try:
                gitlab_cli.delete_branch(branch=self.branch)
                self.branch_created = False
            except GitlabError as gitlab_error:
                # we are not going to let an otherwise fine MR
                # processing fail just because of this
                LOG.error(
                    f"Failed to delete branch {self.branch}. " f"Reason: {gitlab_error}"
                )

    def diffs(self, gitlab_cli: GitLabApi) -> Any:
        return gitlab_cli.project.repository_compare(
            from_=gitlab_cli.main_branch, to=self.branch
        )["diffs"]

    def submit(self, cli: MRClient) -> Union[Any, None]:
        if isinstance(cli, GitLabApi):
            return self.submit_to_gitlab(gitlab_cli=cli)

        if isinstance(cli, SQSGateway):
            self.submit_to_sqs(sqs_cli=cli)
            return None

        raise AttributeError(f"client {cli} not supported")


def app_interface_email(
    name: str,
    subject: str,
    body: str,
    users: Optional[list[str]] = None,
    aliases: Optional[list[str]] = None,
    aws_accounts: Optional[list[str]] = None,
    apps: Optional[list[str]] = None,
) -> str:
    """Render app-interface-email template."""
    with open(EMAIL_TEMPLATE, encoding="locale") as file_obj:
        email_template = Template(
            file_obj.read(), keep_trailing_newline=True, trim_blocks=True
        )

    return email_template.render(
        NAME=name,
        SUBJECT=subject,
        BODY=body,
        USERS=users,
        ALIASES=aliases,
        AWS_ACCOUNTS=aws_accounts,
        SERVICES=apps,
    )
