import logging

from dateutil import parser as dateparser

import utils.threaded as threaded

from reconcile import queries
from utils.gitlab_api import GitLabApi
from utils.gitlab_api import MRState
from utils.repo_owners import RepoOwners

QONTRACT_INTEGRATION = 'gitlab-owners'

APPROVAL_LABEL = 'bot/approved'
COMMENT_PREFIX = '[OWNERS]'

_LOG = logging.getLogger(__name__)


class OwnerNotFoundError(Exception):
    """
    Used when an owner is not found for a change.
    """


class MRApproval:
    """
    Processes a Merge Request, looking for matches
    between the approval messages the the project owners.
    """
    def __init__(self, gitlab_client, merge_request, owners, dry_run):
        self.gitlab = gitlab_client
        self.mr = merge_request
        self.owners = owners
        self.dry_run = dry_run

        commits = self.mr.commits()
        if commits:
            top_commit = next(commits)
            self.top_commit_created_at = \
                dateparser.parse(top_commit.created_at)
        else:
            self.top_commit_created_at = None

    def get_change_owners_map(self):
        """
        Maps each change path to the list of owners that can approve
        that change.
        """
        change_owners_map = dict()
        paths = self.gitlab.get_merge_request_changed_paths(self.mr.iid)
        for path in paths:
            owners = self.owners.get_path_owners(path)
            path_approvers = owners['approvers']
            path_reviewers = owners['reviewers']
            if not path_approvers:
                raise OwnerNotFoundError(f'No owners for path {path!r}')

            closest_owners = self.owners.get_path_closest_owners(path)
            closest_approvers = closest_owners['approvers']
            closest_reviewers = closest_owners['reviewers']

            change_owners_map[path] = {'approvers': path_approvers,
                                       'reviewers': path_reviewers,
                                       'closest_approvers': closest_approvers,
                                       'closest_reviewers': closest_reviewers}
        return change_owners_map

    def get_lgtms(self):
        """
        Collects the usernames of all the '/lgtm' comments.
        """
        lgtms = []
        comments = self.gitlab.get_merge_request_comments(self.mr.iid)
        for comment in comments:

            # Only interested in '/lgtm' comments
            if comment['body'] != '/lgtm':
                continue

            # Only interested in comments created after the top commit
            # creation time
            comment_created_at = dateparser.parse(comment['created_at'])
            if comment_created_at < self.top_commit_created_at:
                continue

            lgtms.append(comment['username'])
        return lgtms

    def get_approval_status(self):
        approval_status = {'approved': False,
                           'report': None}

        try:
            change_owners_map = self.get_change_owners_map()
        except OwnerNotFoundError:
            # When a change has no candidate owner, we can't
            # auto-approve the MR
            return approval_status

        if not change_owners_map:
            return approval_status

        report = {}
        lgtms = self.get_lgtms()

        approval_status['approved'] = True
        for change_path, change_owners in change_owners_map.items():
            change_approved = False
            for approver in change_owners['approvers']:
                if approver in lgtms:
                    change_approved = True

            # Each change that was not yet approved will generate
            # a report message
            report[change_path] = {}
            if not change_approved:
                approval_status['approved'] = False
                approvers = change_owners['closest_approvers']
                report[change_path]['approvers'] = approvers

            change_reviewed = False
            for reviewer in change_owners['reviewers']:
                if reviewer in lgtms:
                    change_reviewed = True

            if not change_reviewed:
                reviewers = change_owners['closest_reviewers']
                report[change_path]['reviewers'] = reviewers

        # Returning earlier. No need to process comments if
        # we got no report.
        if not report:
            return approval_status

        # Now, since we have a report, let's check if that report was
        # already used for a comment
        formatted_report = self.format_report(report)
        comments = self.gitlab.get_merge_request_comments(self.mr.iid)
        for comment in comments:
            # Only interested on our own comments
            if comment['username'] != self.gitlab.user.username:
                continue

            # Ignoring non-approval comments
            body = comment['body']
            if not body.startswith(COMMENT_PREFIX):
                continue

            # If the comment was created before the last commit,
            # it means we had a push after the comment. In this case,
            # we delete the comment and move on.
            comment_created_at = dateparser.parse(comment['created_at'])
            if comment_created_at < self.top_commit_created_at:

                # Deleting stale comments
                _LOG.info([f'Project:{self.gitlab.project.id} '
                           f'Merge Request:{self.mr.iid} '
                           f'- removing stale comment'])
                if not self.dry_run:
                    self.gitlab.delete_gitlab_comment(self.mr.iid,
                                                      comment['id'])
                continue

            # At this point, we've found an approval comment comment
            # made after the last push. Now we just have to check
            # whether the comment has the current report information.
            # When that's the case, we return no report so no new comment
            # will be posted.
            if body == formatted_report:
                return approval_status

        # At this point, the MR was not fully approved and there's no
        # comment reflecting the current approval status. The report will
        # be used for creating a comment in the MR.
        approval_status['report'] = formatted_report
        return approval_status

    def has_approval_label(self):
        labels = self.gitlab.get_merge_request_labels(self.mr.iid)
        return APPROVAL_LABEL in labels

    @staticmethod
    def format_report(report):
        """
        Gets a report dictionary and creates the corresponding Markdown
        comment message.
        """
        markdown_report = (f'{COMMENT_PREFIX} You will need a "/lgtm" from'
                           f'one person from each of these groups:\n\n')

        approvers = list()
        for _, owners in report.items():
            new_group = list()

            if 'approvers' not in owners:
                continue

            for owner in owners['approvers']:
                there = False

                for group in approvers:
                    if owner in group:
                        there = True

                if not there:
                    new_group.append(owner)

            if new_group:
                approvers.append(new_group)

        for group in approvers:
            markdown_report += f'* {", ".join(group)}\n'

        markdown_report += '\nAdditional relevant reviewers are: '

        reviewers = set()
        for _, owners in report.items():
            if 'reviewers' not in owners:
                continue

            for reviewer in owners['reviewers']:

                there = False
                for group in approvers:
                    if reviewer in group:
                        there = True

                if not there:
                    reviewers.add(reviewer)

        markdown_report += f'{", ".join(sorted(reviewers))}'

        return markdown_report


def act(repo, dry_run, instance, settings):
    gitlab_cli = GitLabApi(instance, project_url=repo, settings=settings)
    project_owners = RepoOwners(git_cli=gitlab_cli)

    for mr in gitlab_cli.get_merge_requests(state=MRState.OPENED):
        mr_approval = MRApproval(gitlab_client=gitlab_cli,
                                 merge_request=mr,
                                 owners=project_owners,
                                 dry_run=dry_run)

        if mr_approval.top_commit_created_at is None:
            _LOG.info([f'Project:{gitlab_cli.project.id} '
                       f'Merge Request:{mr.iid} '
                       f'- skipping'])
            continue

        approval_status = mr_approval.get_approval_status()
        if approval_status['approved']:
            if mr_approval.has_approval_label():
                _LOG.info([f'Project:{gitlab_cli.project.id} '
                           f'Merge Request:{mr.iid} '
                           f'- already approved'])
                continue
            _LOG.info([f'Project:{gitlab_cli.project.id} '
                       f'Merge Request:{mr.iid} '
                       f'- approving now'])
            if not dry_run:
                gitlab_cli.add_label_to_merge_request(mr.iid,
                                                      APPROVAL_LABEL)
            continue

        if not dry_run:
            if mr_approval.has_approval_label():
                _LOG.info([f'Project:{gitlab_cli.project.id} '
                           f'Merge Request:{mr.iid} '
                           f'- removing approval'])
                gitlab_cli.remove_label_from_merge_request(mr.iid,
                                                           APPROVAL_LABEL)

        if approval_status['report'] is not None:
            _LOG.info([f'Project:{gitlab_cli.project.id} '
                       f'Merge Request:{mr.iid} '
                       f'- publishing approval report'])

            if not dry_run:
                gitlab_cli.remove_label_from_merge_request(mr.iid,
                                                           APPROVAL_LABEL)
                mr.notes.create({'body': approval_status['report']})
            continue

        _LOG.info([f'Project:{gitlab_cli.project.id} '
                   f'Merge Request:{mr.iid} '
                   f'- not fully approved'])


def run(dry_run, thread_pool_size=10):
    instance = queries.get_gitlab_instance()
    settings = queries.get_app_interface_settings()
    repos = queries.get_repos_gitlab_owner(server=instance['url'])
    threaded.run(act, repos, thread_pool_size,
                 dry_run=dry_run,
                 instance=instance,
                 settings=settings)
