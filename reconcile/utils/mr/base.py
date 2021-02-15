import logging

from abc import abstractmethod
from abc import ABCMeta
from uuid import uuid4

from gitlab.exceptions import GitlabError

from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.sqs_gateway import SQSGateway

from reconcile.utils.mr.labels import DO_NOT_MERGE


LOG = logging.getLogger(__name__)


class CancelMergeRequest(Exception):
    """
    Used when the Merge Request processing is canceled.
    """


class MergeRequestBase(metaclass=ABCMeta):
    """
    Base abstract class for all merge request types.
    """

    name = 'merge-request-base'

    def __init__(self):
        # Let's first get all the attributes from the instance
        # and use for the SQS Msg payload. With that, the msg
        # to the SQS is enough to create a new, similar, instance
        # of the child class.
        self.sqs_msg_data = {**self.__dict__}

        self.gitlab_cli = None
        self.labels = [DO_NOT_MERGE]

        random_id = str(uuid4())[:6]
        self.branch = f'{self.name}-{random_id}'

        self.main_branch = 'master'
        self.remove_source_branch = True

    @staticmethod
    def cancel(message):
        raise CancelMergeRequest(message)

    @abstractmethod
    def title(self):
        """
        Title of the Merge Request.

        :return: Merge Request title as seen in the Gitlab Web UI
        :rtype: str
        """

    @abstractmethod
    def process(self, gitlab_cli):
        """
        Called by `submit_to_gitlab`, this method is the place for
        user-defined steps to create the commits of a merge request.

        :param gitlab_cli:
        :type gitlab_cli: GitLabApi
        """

    @property
    def sqs_data(self):
        """
        The SQS Message payload (MessageBody) generated out of
        the Merge Request class instance.
        """
        return {
            'pr_type': self.name,
            **self.sqs_msg_data,
        }

    def submit_to_sqs(self, sqs_cli):
        """
        Sends the MR message to SQS.

        :param sqs_cli: The SQS Client instance.
        :type sqs_cli: SQSGateway
        """
        sqs_cli.send_message(self.sqs_data)

    @property
    def gitlab_data(self):
        """
        The Gitlab payload for creating the Merge Request.
        """
        return {
            'source_branch': self.branch,
            'target_branch': self.main_branch,
            'title': self.title,
            'remove_source_branch': self.remove_source_branch,
            'labels': self.labels
        }

    def submit_to_gitlab(self, gitlab_cli):
        """
        :param gitlab_cli:
        :type gitlab_cli: GitLabApi
        """
        """
        Sends the MR to Gitlab.

        :param gitlab_cli: The SQS Client instance.
        :type gitlab_cli: GitLabApi
        """
        # Avoiding duplicate MRs
        if gitlab_cli.mr_exists(title=self.title):
            LOG.info('MR with the same name already exists. '
                     'Aborting MR creation.')
            return

        gitlab_cli.create_branch(new_branch=self.branch,
                                 source_branch=self.main_branch)

        try:
            self.process(gitlab_cli=gitlab_cli)
        except (CancelMergeRequest, GitlabError) as details:
            gitlab_cli.delete_branch(branch=self.branch)
            LOG.info(details)
            return

        # Avoiding empty MRs
        if not gitlab_cli.project.repository_compare(from_=self.main_branch,
                                                     to=self.branch)['diffs']:
            gitlab_cli.delete_branch(branch=self.branch)
            LOG.info('No changes when compared to %s. Aborting MR creation.',
                     self.main_branch)
            return

        return gitlab_cli.project.mergerequests.create(self.gitlab_data)

    def submit(self, cli):
        if isinstance(cli, GitLabApi):
            return self.submit_to_gitlab(gitlab_cli=cli)

        if isinstance(cli, SQSGateway):
            return self.submit_to_sqs(sqs_cli=cli)

        raise AttributeError(f'client {cli} not supported')
