import logging

from typing import (
    Any,
    Optional,
    Union,
)

from collections.abc import (
    Iterable,
)

from reconcile import queries
import reconcile.utils.jira_client as J
import reconcile.utils.gitlab_api as G
from reconcile.utils.mr.labels import (
    DO_NOT_MERGE_HOLD,
)

QONTRACT_INTEGRATION = "change-control-automation"
DATE_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"

RECORD_ACTIONS = ["/standard"]
REQUEST_ACTIONS = ["/major"]
ACTIVE_TICKET_LABEL_STATES = ["cr-approving"]
TERMINAL_TICKET_LABEL_STATES = ["cr-active", "cr-approved", "cr-denied"]

REQUEST_ISSUETYPE_ID = "10201"
RECORD_ISSUETYPE_ID = "10500"
RECORD_TICKET_STATES = {"TO_DO": 11, "IN_PROGRESS": 21, "DONE": 31}
REQUEST_TICKET_STATES = {
    "REQUEST_PEER_REVIEW": 11,
}
REQUEST_TICKET_APPROVED_STATE = "Awaiting implementation"
REQUEST_TICKET_DENIED_STATE = "Declined"

COMMENT_COMMANDS = """Code updates to this repository require a Change Record (standard changes) or a Change Request (major changes).
\n\n
Commands:\n\n

* /standard: create a Change Record for standard changes
* /major: create a Change Request for major changes"""
COMMENT_LABEL_STATES = """After applying a label command to an MR, automation will update the label to represent the current state of the associated Jira issue.\n\n

Label states:\n\n

* cr-active (Change Record created)
* cr-approved (Change Request approved)
* cr-denied (Change Request denied)"""
COMMENT_PROTECTION = "Change requests must be approved by the CCB before merging. Merge protection enabled."
COMMENT_REQUEST_APPROVED = (
    "CCB approved this change request. Merge protection disabled."
)
COMMENT_REQUEST_DENIED = "CCB denied this change request. Closing MR."


def run(dry_run):
    gitlab_instance = queries.get_gitlab_instance()
    settings = queries.get_app_interface_settings()
    projects = queries.get_projects_change_control_automation()

    for project in projects:
        handle = GitlabJiraChangeControl()
        handle.work()


class GitlabJiraChangeControl:
    """
    GitlabJiraChangeControl implements a time-saving interface for engineers to automatically generate Jira change control tickets from their GitLab merge request metadata.
    From a high level, the class sets up handles to GitLab and Jira and works on a specific Gitlab project. For each open MR, the class uses gitlab labels and jira tickets to manage the state of change records and change requests.
    """

    def __init__(
        self, secret_reader=None, jira=None, gitlab=None, dry_run=False, project_id=7
    ) -> None:
        self.project_id = project_id
        self.jira_url = ""
        self.jira_board = ""

        self.gl = G.GitLabApi(
            instance={
                "url": "",
                "token": "",
                "sslVerify": False,
            },
            project_id=project_id,
        )

        self.j = J.JiraClient(
            jira_board={
                "name": self.jira_board,
                "server": {
                    "serverUrl": self.jira_url,
                    "token": "",
                },
            }
        )

        self.dry_run = dry_run
        logging.info(
            [
                "GitlabJiraChangeControl class instantiated",
                f"dry_run={self.dry_run}",
                f"project_id={project_id}",
            ]
        )

    def work(self) -> None:
        """
        work() is the primary entry point for processing a project's MRs. work() polls for all open merge requests, and then processes them depending on their state and interactions with GitLab and Jira.
        """
        logging.debug(["work() start"])
        all_mrs = self.gl.get_merge_requests(state=G.MRState.OPENED)
        logging.info(["open mrs", all_mrs])
        for mr in all_mrs:
            self.process_mr(mr.iid)

    def process_mr(self, mr_iid: int) -> None:
        """Given an mr iid, do all the change control things:
        * Figure out if this integration has seen the MR before
        * Populate MR with command and states comments
        * Determine if MR has an existing issue
        * Trigger actions on existing MR / issue combos
        * Trigger actions for a new MR
        * Determine if issue is request or record
        * Act on request creation
        * Act on record creation
        """
        logging.debug(["process_mr() start", f"iid={mr_iid}"])

        # Gather data on MR, labels, comments, and jira issue
        # Use labels and comment_state to decide what to do next
        mr = self.gl.get_merge_request(mr_iid)
        commit_hash = self.gl.get_merge_request_first_commit_hash(mr_iid)
        mr_labels = self.gl.get_merge_request_labels(mr_iid)
        comments = self.gl.get_merge_request_comments(mr_iid)
        comment_state = self.process_comments(comments)

        if any(label in mr_labels for label in TERMINAL_TICKET_LABEL_STATES):
            # create_issue already ran for this mr / issue combination
            # The issue already exists. We should see if we need to do anything.
            logging.debug(
                [
                    f"process_mr()",
                    f"iid={mr_iid}",
                    "existing issue state found in mr labels",
                ]
            )

            # We only do something for change requests, not change records.
            if any(label in mr_labels for label in ACTIVE_TICKET_LABEL_STATES):
                self.handle_active_change_request(mr, commit_hash)

        else:
            # The issue does not exist. Process the comments to find next steps.
            logging.debug(
                [
                    f"process_mr()",
                    f"iid={mr_iid}",
                    "existing issue state not found in mr labels",
                ]
            )

            # Add the help comments if needed
            self.add_helpers_to_comments(
                mr_iid, comment_state["seen_command"], comment_state["seen_state"]
            )

            # Choose request or record actions if applicable
            if comment_state["seen_act_request"]:
                self.create_issue(mr, commit_hash, request=True)
            elif comment_state["seen_act_record"]:
                self.create_issue(mr, commit_hash, request=False)

    def process_comments(
        self, comments: Iterable[Any]
    ) -> Mapping[str, str]:  # Improve with jira.resources.Comment type?
        """
        Figure out what to do next based on comments
        This method only gets called if an existing issue state does not exist
        Stops processing comments when a single hit happens for a given state
        Options:
        * Add helper comment - commands
        * Add helper comment - state
        * See record command
        * See request command
        """

        output = {
            "seen_command": False,
            "seen_state": False,
            "seen_act_record": False,
            "seen_act_request": False,
        }

        for comment in comments:
            if not output["seen_command"] and comment["body"] == COMMENT_COMMANDS:
                output["seen_command"] = True
            elif not output["seen_state"] and comment["body"] == COMMENT_LABEL_STATES:
                output["seen_state"] = True
            elif not output["seen_act_record"] and RECORD_ACTIONS.count(
                comment["body"]
            ):
                output["seen_act_record"] = True
            elif not output["seen_act_request"] and REQUEST_ACTIONS.count(
                comment["body"]
            ):
                output["seen_act_request"] = True

        return output

    def add_helpers_to_comments(
        self, mr_iid: int, commands: bool, states: bool
    ) -> None:
        # Add helper comments given falsy for input
        if not commands:
            logging.debug(["add commands comment"])

            if not self.dry_run:
                self.gl.add_merge_request_comment(mr_iid, COMMENT_COMMANDS)

        if not states:
            logging.debug(["add states comment"])

            if not self.dry_run:
                self.gl.add_merge_request_comment(mr_iid, COMMENT_LABEL_STATES)

    def add_jira_link_comment(
        self, mr_iid: int, issue_permalink: str, request: bool = False
    ) -> None:
        #
        logging.debug(["add jira link comment"])
        issue_link = f"Issue link: {issue_permalink}"

        if not self.dry_run:
            self.gl.add_merge_request_comment(mr_iid, issue_link)

            if request:
                protection = COMMENT_PROTECTION
                self.gl.add_merge_request_comment(mr_iid, protection)

    def add_decision_comment(self, mr_iid: int, approved: bool = False) -> None:
        logging.debug(["add ccb approval comment"])

        comment = ""
        if approved:
            comment = COMMENT_REQUEST_APPROVED
        else:
            comment = COMMENT_REQUEST_DENIED

        if not self.dry_run:
            self.gl.add_merge_request_comment(mr_iid, comment)

    def issue_exists(self, commit_hash: str, expected_type: str) -> Iterable[str, str]:
        """
        Try to find the issue by hash
        Also check the issue type and ensure consistency
        """
        output = {"issue": None, "type_match": True}

        find_issue_by_hash = self.j.get_issues(custom_jql=f"Labels = {commit_hash}")

        if find_issue_by_hash:
            output["issue"] = find_issue_by_hash[0]
            output["type_match"] = (
                output["issue"].fields.issuetype.name == expected_type
            )

        # Commit history rebased or issue does not exist
        return output

    def generate_issue_metadata(
        self, mr: Any, commit_hash: str, request: bool = False
    ) -> Iterable[str, Any]:
        """
        Generate a new issue from an GitLab MR object
        Output is either a Record or a Request
        """
        title = mr.attributes.get("title")
        description = mr.attributes.get("description")
        author_dict = mr.attributes.get("author")
        author_username = author_dict["username"]

        new_issue = {
            "summary": f"{title}",
            "body": f"{description}",
            "labels": [f"{commit_hash}"],
            "issuetype": "Change Request" if request else "Change Record",
            "assignee": {"name": f"{author_username}"},
        }

        return new_issue

    def create_issue(self, mr: Any, commit_hash: str, request: bool = False) -> None:
        # Handle creation of change records
        logging.info(
            ["create_issue() start", mr.iid, commit_hash, f"request={request}"]
        )

        # check for duplicates and issue type match
        expected_type = "Change Request" if request else "Change Record"
        found_issue_info = self.issue_exists(commit_hash, expected_type)

        found_issue = found_issue_info["issue"]
        type_match = found_issue_info["type_match"]

        issue = None
        if found_issue and not type_match:
            issue = self.manage_type_mismatch(commit_hash, found_issue, request=request)
        elif found_issue:
            issue = found_issue
            logging.info(["existing issue found", issue.id])
        else:
            new_issue = self.generate_issue_metadata(mr, commit_hash, request=request)
            logging.info(["create new jira issue", new_issue])

            if not self.dry_run:
                issue = self.j.create_issue(**new_issue)

                if issue:
                    self.add_jira_link_comment(
                        mr.iid, issue.permalink(), request=request
                    )

                    logging.debug(["add labels, transition issue state"])
                    if request:
                        # Change Request
                        self.gl.add_label_to_merge_request(mr.iid, DO_NOT_MERGE_HOLD)
                        self.gl.add_label_to_merge_request(mr.iid, "cr-active")
                        self.gl.add_label_to_merge_request(mr.iid, "cr-approving")
                        self.j.jira.transition_issue(
                            issue, REQUEST_TICKET_STATES["REQUEST_PEER_REVIEW"]
                        )
                    else:
                        # Change Record
                        self.gl.add_label_to_merge_request(mr.iid, "cr-active")
                        self.j.jira.transition_issue(
                            issue, RECORD_TICKET_STATES["IN_PROGRESS"]
                        )

    def handle_active_change_request(self, mr: Any, commit_hash: str) -> None:
        """
        For an open change request, check the issue status and see if an update happened.
        The only states we take action on are after CAB approval and CAB denial
        """

        logging.info(["handle_active_change_request()", mr.iid, commit_hash])
        issues = self.j.get_issues(custom_jql=f"Labels = {commit_hash}")

        if issues:
            issue = issues[0]
            status = issue.fields.status.name

            if status == REQUEST_TICKET_APPROVED_STATE:
                logging.info(
                    ["handle_active_change_request()", mr.iid, commit_hash, "approved"]
                )
                self.add_decision_comment(mr.iid, approved=True)
                self.gl.remove_label_from_merge_request(mr.iid, DO_NOT_MERGE_HOLD)
                self.gl.remove_label_from_merge_request(mr.iid, "cr-approving")
                self.gl.add_label_to_merge_request(mr.iid, "cr-approved")

            elif status == REQUEST_TICKET_DENIED_STATE:
                logging.info(
                    ["handle_active_change_request()", mr.iid, commit_hash, "denied"]
                )
                self.add_decision_comment(mr.iid, approved=False)
                self.gl.remove_label_from_merge_request(mr.iid, "cr-approving")
                self.gl.add_label_to_merge_request(mr.iid, "cr-denied")
                self.gl.close(mr)

            else:
                logging.info(
                    ["handle_active_change_request()", mr.iid, commit_hash, "no action"]
                )

        else:
            logging.warn(
                [
                    "handle_active_change_request()",
                    mr.iid,
                    commit_hash,
                    "issue expected, not found",
                ]
            )
