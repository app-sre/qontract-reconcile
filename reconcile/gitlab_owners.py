import logging

from dateutil import parser as dateparser
from sretoolbox.utils import threaded

from reconcile import queries
from reconcile.utils.defer import defer
from reconcile.utils.gitlab_api import (
    GitLabApi,
    MRState,
)
from reconcile.utils.mr.labels import APPROVED
from reconcile.utils.repo_owners import RepoOwners

QONTRACT_INTEGRATION = "gitlab-owners"

COMMENT_PREFIX = "[OWNERS]"

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

    def __init__(self, gitlab_client, merge_request, owners, dry_run, persistent_lgtm):
        self.gitlab = gitlab_client
        self.mr = merge_request
        self.owners = owners
        self.dry_run = dry_run
        self.persistent_lgtm = persistent_lgtm

        # Get the date of the most recent commit (top commit) in the MR, but avoid comparing against None
        self.top_commit_created_at = dateparser.parse("2000-01-01")
        commits = self.mr.commits()
        if commits:
            top_commit = next(commits)
            self.top_commit_created_at = dateparser.parse(top_commit.created_at)

    def get_change_owners_map(self):
        """
        Maps each change path to the list of owners that can approve
        that change.
        """
        change_owners_map = {}
        paths = self.gitlab.get_merge_request_changed_paths(self.mr.iid)
        for path in paths:
            owners = self.owners.get_path_owners(path)
            path_approvers = owners["approvers"]
            path_reviewers = owners["reviewers"]
            if not path_approvers:
                raise OwnerNotFoundError(f"No owners for path {path!r}")

            closest_owners = self.owners.get_path_closest_owners(path)
            closest_approvers = closest_owners["approvers"]
            closest_reviewers = closest_owners["reviewers"]

            change_owners_map[path] = {
                "approvers": path_approvers,
                "reviewers": path_reviewers,
                "closest_approvers": closest_approvers,
                "closest_reviewers": closest_reviewers,
            }
        return change_owners_map

    def get_lgtms(self):
        """
        Collects the usernames of all the '/lgtm' comments.
        """
        lgtms = []
        comments = self.gitlab.get_merge_request_comments(self.mr.iid)
        for comment in comments:
            # Only interested in '/lgtm' comments
            if comment["body"] != "/lgtm":
                continue

            # Only interested in comments created after the top commit
            # creation time
            comment_created_at = dateparser.parse(comment["created_at"])
            if (
                comment_created_at < self.top_commit_created_at
                and not self.persistent_lgtm
            ):
                continue

            lgtms.append(comment["username"])
        return lgtms

    def get_approval_status(self):
        approval_status = {"approved": False, "report": None}

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

        approval_status["approved"] = True
        for change_path, change_owners in change_owners_map.items():
            change_approved = False
            for approver in change_owners["approvers"]:
                if approver in lgtms:
                    change_approved = True

            # Each change that was not yet approved will generate
            # a report message
            report[change_path] = {}
            if not change_approved:
                approval_status["approved"] = False
                approvers = change_owners["approvers"]
                report[change_path]["approvers"] = approvers
                closest_approvers = change_owners["closest_approvers"]
                report[change_path]["closest_approvers"] = closest_approvers

            change_reviewed = False
            for reviewer in change_owners["reviewers"]:
                if reviewer in lgtms:
                    change_reviewed = True

            if not change_reviewed:
                reviewers = change_owners["reviewers"]
                report[change_path]["reviewers"] = reviewers
                closest_reviewers = change_owners["closest_reviewers"]
                report[change_path]["closest_reviewers"] = closest_reviewers

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
            if comment["username"] != self.gitlab.user.username:
                continue

            # Ignoring non-approval comments
            body = comment["body"]
            if not body.startswith(COMMENT_PREFIX):
                continue

            # If the comment was created before the last commit,
            # it means we had a push after the comment. In this case,
            # we delete the comment and move on.
            comment_created_at = dateparser.parse(comment["created_at"])
            if comment_created_at < self.top_commit_created_at:
                # Deleting stale comments
                _LOG.info(
                    [
                        f"Project:{self.gitlab.project.id} "
                        f"Merge Request:{self.mr.iid} "
                        f"- removing stale comment"
                    ]
                )
                if not self.dry_run:
                    self.gitlab.delete_gitlab_comment(comment["note"])
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
        approval_status["report"] = formatted_report
        return approval_status

    def has_approval_label(self):
        labels = self.gitlab.get_merge_request_labels(self.mr.iid)
        return APPROVED in labels

    @staticmethod
    def format_report(report):
        """
        Gets a report dictionary and creates the corresponding Markdown
        comment message.
        """
        markdown_report = ""

        closest_approvers = []
        for _, owners in report.items():
            new_group = []

            if "closest_approvers" not in owners:
                continue

            for closest_approver in owners["closest_approvers"]:
                there = False

                for group in closest_approvers:
                    if closest_approver in group:
                        there = True

                if not there:
                    new_group.append(closest_approver)

            if new_group:
                closest_approvers.append(new_group)

        if closest_approvers:
            if len(closest_approvers) == 1:
                markdown_report += (
                    f"{COMMENT_PREFIX} You will need a "
                    f'"/lgtm" from at least one person from '
                    f"the following group:\n\n"
                )
            else:
                markdown_report += (
                    f"{COMMENT_PREFIX} You will need a "
                    f'"/lgtm" from at least one person from '
                    f"each of the following groups:\n\n"
                )

        for group in sorted(closest_approvers):
            markdown_report += f'* {", ".join(group)}\n'

        approvers = set()
        for _, owners in report.items():
            if "approvers" not in owners:
                continue

            for approver in owners["approvers"]:
                there = False

                for group in closest_approvers:
                    if approver in group:
                        there = True

                if not there:
                    approvers.add(approver)

        if approvers:
            markdown_report += (
                "\nIn case of emergency, the override approvers "
                "(from parent directories) are:\n\n"
            )
            markdown_report += f'* {", ".join(sorted(approvers))}\n'

        closest_reviewers = set()
        for _, owners in report.items():
            if "closest_reviewers" not in owners:
                continue

            for closest_reviewer in owners["closest_reviewers"]:
                there = False
                for group in closest_approvers:
                    if closest_reviewer in group:
                        there = True

                if closest_reviewer in approvers:
                    there = True

                if not there:
                    closest_reviewers.add(closest_reviewer)

        if closest_reviewers:
            markdown_report += "\nRelevant reviewers (with no " "merge rights) are:\n\n"
            markdown_report += f'* {", ".join(sorted(closest_reviewers))}\n'

        reviewers = set()
        for _, owners in report.items():
            if "reviewers" not in owners:
                continue

            for reviewer in owners["reviewers"]:
                there = False
                for group in closest_approvers:
                    if reviewer in group:
                        there = True

                if reviewer in approvers:
                    there = True

                if reviewer in closest_reviewers:
                    there = True

                if not there:
                    reviewers.add(reviewer)

        if reviewers:
            markdown_report += (
                "\nOther reviewers (with no "
                "merge rights) from parent "
                "directories are:\n\n"
            )
            markdown_report += f'* {", ".join(sorted(reviewers))}\n'

        return markdown_report.rstrip()


@defer
def act(repo, dry_run, instance, settings, defer=None):
    gitlab_cli = GitLabApi(instance, project_url=repo["url"], settings=settings)
    defer(gitlab_cli.cleanup)
    project_owners = RepoOwners(
        git_cli=gitlab_cli, ref=gitlab_cli.project.default_branch
    )

    for mr in gitlab_cli.get_merge_requests(state=MRState.OPENED):
        mr_approval = MRApproval(
            gitlab_client=gitlab_cli,
            merge_request=mr,
            owners=project_owners,
            dry_run=dry_run,
            persistent_lgtm=repo.get("gitlabRepoOwners", {}).get("persistentLgtm", None)
            or False,
        )

        if mr_approval.top_commit_created_at is None:
            _LOG.info(
                [
                    f"Project:{gitlab_cli.project.id} "
                    f"Merge Request:{mr.iid} "
                    f"- skipping"
                ]
            )
            continue

        approval_status = mr_approval.get_approval_status()
        if approval_status["approved"]:
            if mr_approval.has_approval_label():
                _LOG.info(
                    [
                        f"Project:{gitlab_cli.project.id} "
                        f"Merge Request:{mr.iid} "
                        f"- already approved"
                    ]
                )
                continue
            _LOG.info(
                [
                    f"Project:{gitlab_cli.project.id} "
                    f"Merge Request:{mr.iid} "
                    f"- approving now"
                ]
            )
            if not dry_run:
                gitlab_cli.add_label_to_merge_request(mr.iid, APPROVED)
            continue

        if not dry_run:
            if mr_approval.has_approval_label():
                _LOG.info(
                    [
                        f"Project:{gitlab_cli.project.id} "
                        f"Merge Request:{mr.iid} "
                        f"- removing approval"
                    ]
                )
                gitlab_cli.remove_label(mr, APPROVED)

        if approval_status["report"] is not None:
            _LOG.info(
                [
                    f"Project:{gitlab_cli.project.id} "
                    f"Merge Request:{mr.iid} "
                    f"- publishing approval report"
                ]
            )

            if not dry_run:
                gitlab_cli.remove_label(mr, APPROVED)
                mr.notes.create({"body": approval_status["report"]})
            continue

        _LOG.info(
            [
                f"Project:{gitlab_cli.project.id} "
                f"Merge Request:{mr.iid} "
                f"- not fully approved"
            ]
        )


def run(dry_run, thread_pool_size=10):
    instance = queries.get_gitlab_instance()
    settings = queries.get_app_interface_settings()
    repos = queries.get_repos_gitlab_owner(server=instance["url"])
    threaded.run(
        act,
        repos,
        thread_pool_size,
        dry_run=dry_run,
        instance=instance,
        settings=settings,
    )
