import logging
import sys
import traceback

from gitlab.v4.objects import ProjectMergeRequest

from reconcile import queries
from reconcile.change_owners.approver import GqlApproverResolver
from reconcile.change_owners.bundle import (
    FileDiffResolver,
    QontractServerFileDiffResolver,
)
from reconcile.change_owners.change_types import (
    ChangeTypeContext,
    ChangeTypePriority,
    ChangeTypeProcessor,
    init_change_type_processors,
)
from reconcile.change_owners.changes import (
    BundleFileChange,
    fetch_bundle_changes,
    get_priority_for_changes,
)
from reconcile.change_owners.decision import (
    ChangeDecision,
    ChangeResponsibles,
    DecisionCommand,
    apply_decisions_to_changes,
    get_approver_decisions_from_mr_comments,
)
from reconcile.change_owners.implicit_ownership import (
    cover_changes_with_implicit_ownership,
)
from reconcile.change_owners.self_service_roles import (
    cover_changes_with_self_service_roles,
    fetch_self_service_roles,
)
from reconcile.gql_definitions.change_owners.queries import change_types
from reconcile.utils import gql
from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.mr.labels import (
    HOLD,
    NOT_SELF_SERVICEABLE,
    RESTRICTED,
    SELF_SERVICEABLE,
    change_owner_label,
    prioritized_approval_label,
)
from reconcile.utils.output import format_table
from reconcile.utils.semver_helper import make_semver

QONTRACT_INTEGRATION = "change-owners"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)


class NotAdmittedError(Exception):
    pass


def cover_changes(
    changes: list[BundleFileChange],
    change_type_processors: list[ChangeTypeProcessor],
    comparision_gql_api: gql.GqlApi,
) -> None:
    """
    Coordinating function that can reach out to different `cover_*` functions
    leveraging different approver contexts.
    """

    # self service roles coverage
    roles = fetch_self_service_roles(comparision_gql_api)
    cover_changes_with_self_service_roles(
        bundle_changes=changes,
        change_type_processors=change_type_processors,
        roles=roles,
    )

    # implicit ownership coverage
    cover_changes_with_implicit_ownership(
        bundle_changes=changes,
        change_type_processors=[
            ct for ct in change_type_processors if ct.implicit_ownership
        ],
        approver_resolver=GqlApproverResolver([comparision_gql_api, gql.get_api()]),
    )


def fetch_change_type_processors(
    gql_api: gql.GqlApi, file_diff_resolver: FileDiffResolver
) -> list[ChangeTypeProcessor]:
    change_type_list = change_types.query(gql_api.query).change_types or []
    return list(
        init_change_type_processors(change_type_list, file_diff_resolver).values()
    )


CHANGE_TYPE_PROCESSING_MODE_LIMITED = "limited"
CHANGE_TYPE_PROCESSING_MODE_AUTHORITATIVE = "authoritative"


def manage_conditional_label(
    current_labels: list[str],
    conditional_labels: dict[str, bool],
    dry_run: bool = True,
) -> set[str]:
    new_labels = current_labels.copy()
    for label, condition in conditional_labels.items():
        if condition and label not in new_labels:
            logging.info(f"adding label {label}")
            if not dry_run:
                new_labels.append(label)
        elif not condition and label in new_labels:
            logging.info(f"removing label {label}")
            if not dry_run:
                new_labels.remove(label)
    return set(new_labels)


def build_status_message(
    self_serviceable: bool,
    authoritative: bool,
    change_admitted: bool,
    approver_reachability: set[str],
    supported_commands: list[str],
) -> str:
    """
    Build a user-friendly status message based on the MR state.
    """
    approver_section = _build_approver_contact_section(approver_reachability)

    # Check if changes are not admitted (security gate - takes priority)
    if not change_admitted:
        return f"""## ⏸️ Approval Required
Your changes need `/ok-to-test` approval from a listed approver before review can begin.

{approver_section}"""

    commands_text = (
        f"**Available commands:** {' '.join(f'`{cmd}`' for cmd in supported_commands)}"
    )

    code_warning = ""
    if not authoritative:
        code_warning = "⚠️ **Code changes outside of data and resources detected** - please review carefully\n\n"

    if self_serviceable:
        return f"""## ✅ Ready for Review
Get `/lgtm` approval from the listed approvers below.

{code_warning}{approver_section}

{commands_text}"""

    return f"""## 🔍 AppSRE Review Required
**What happens next:**
* AppSRE will review via their [review queue](https://gitlab.cee.redhat.com/service/app-interface-output/-/blob/master/app-interface-review-queue.md)
* Please don't ping directly unless this is **urgent**
* See [etiquette guide](https://gitlab.cee.redhat.com/service/app-interface#app-interface-etiquette) for more info

{code_warning}{approver_section}

{commands_text}"""


def _build_approver_contact_section(approver_reachability: set[str]) -> str:
    """Build the approver contact information section."""
    if not approver_reachability:
        return ""

    return "**Reach out to approvers:**\n" + "\n".join([
        f"* {ar}" for ar in approver_reachability
    ])


def _format_change_responsible(cr: ChangeResponsibles) -> str:
    """
    Format a ChangeResponsibles object.
    """
    usernames = [
        f"@{a.org_username}"
        if (a.tag_on_merge_requests or len(cr.approvers) == 1)
        else a.org_username
        for a in cr.approvers
    ]

    usernames_text = " ".join(usernames)
    return f"<details><summary>{cr.context}</summary>{usernames_text}</details>"


def write_coverage_report_to_mr(
    self_serviceable: bool,
    change_decisions: list[ChangeDecision],
    change_admitted: bool,
    authoritative: bool,
    merge_request: ProjectMergeRequest,
    gl: GitLabApi,
) -> None:
    """
    adds the change coverage report and decision summary as a comment
    to the merge request. this will delete the last report comment and add
    a new one.
    """
    change_coverage_report_header = "Change coverage report"
    # delete previous report comment
    gl.delete_merge_request_comments(
        merge_request,
        startswith=change_coverage_report_header,
    )

    # Build change coverage table
    results = []
    approver_reachability = set()
    for d in change_decisions:
        approvers = [_format_change_responsible(cr) for cr in d.change_responsibles]
        if d.coverable_by_fragment_decisions:
            approvers.append(
                "automatically approved if all sub-properties are approved"
            )
        for cr in d.change_responsibles:
            approver_reachability.update({
                ar.render_for_mr_report() for ar in cr.approver_reachability or []
            })
        if not approvers:
            approvers = ["[- not self-serviceable -]"]
        item = {
            "file": d.file.path,
            "schema": d.file.schema,
            "change": d.diff.path,
        }
        if not change_admitted:
            item["status"] = "restricted"
        elif d.is_held():
            item["status"] = "hold"
        elif d.is_approved():
            item["status"] = "approved"
        item["approvers"] = "".join(approvers)
        results.append(item)

    coverage_report = format_table(
        results, ["file", "change", "status", "approvers"], table_format="github"
    )

    # Build user-friendly status message
    supported_commands = [d.value for d in DecisionCommand]
    status_message = build_status_message(
        self_serviceable=self_serviceable,
        authoritative=authoritative,
        change_admitted=change_admitted,
        approver_reachability=approver_reachability,
        supported_commands=supported_commands,
    )

    # Create the full comment
    full_comment = f"""{change_coverage_report_header}

{status_message}

## 📋 Change Summary
{coverage_report}"""

    gl.add_comment_to_merge_request(merge_request, full_comment)


def write_coverage_report_to_stdout(change_decisions: list[ChangeDecision]) -> None:
    results = []
    for d in change_decisions:
        if d.coverable_by_fragment_decisions:
            results.append({
                "file": d.file.path,
                "schema": d.file.schema,
                "changed path": d.diff.path,
                "change type": "...",
                "origin": "...",
                "context": "coverable by fragments",
                "approver_reachability": "",
                "disabled": False,
            })
        if d.coverage:
            results.extend(
                {
                    "file": d.file.path,
                    "schema": d.file.schema,
                    "changed path": d.diff.path,
                    "change type": ctx.change_type_processor.name,
                    "origin": ctx.origin,
                    "context": ctx.context,
                    "approver_reachability": ", ".join([
                        ar.render_for_mr_report()
                        for ar in ctx.approver_reachability or []
                    ]),
                    "disabled": str(ctx.disabled),
                }
                for ctx in d.coverage
            )
        else:
            results.append({
                "file": d.file.path,
                "schema": d.file.schema,
                "changed path": d.diff.path,
            })

    print(
        format_table(
            results,
            [
                "file",
                "changed path",
                "change type",
                "origin",
                "disabled",
                "context",
                "approver_reachability",
            ],
        )
    )


def init_gitlab(gitlab_project_id: str) -> GitLabApi:
    instance = queries.get_gitlab_instance()
    settings = queries.get_app_interface_settings()
    return GitLabApi(instance, project_id=gitlab_project_id, settings=settings)


def is_coverage_admitted(
    coverage: ChangeTypeContext, mr_author: str, ok_to_test_approvers: set[str]
) -> bool:
    return any(
        a.org_username == mr_author or a.org_username in ok_to_test_approvers
        for a in coverage.approvers
    )


def is_change_admitted(
    changes: list[BundleFileChange], mr_author: str, ok_to_test_approvers: set[str]
) -> bool:
    # Checks if mr authors are allowed to do the changes in the merge request.
    # If a change type is restrictive and the author is not an approver,
    # this is not admitted.
    # A change might be admitted if a user that has the restrictive change
    # type is an approver or an approver adds an /ok-to-test comment.

    restrictive_coverages = [
        c
        for change in changes
        for dc in change.diff_coverage
        for c in dc.coverage
        if c.change_type_processor.restrictive
    ]

    change_types_to_approve = {c.origin for c in restrictive_coverages}
    change_types_approved = {
        c.origin
        for c in restrictive_coverages
        if is_coverage_admitted(c, mr_author, ok_to_test_approvers)
    }
    return change_types_to_approve == change_types_approved


def run(
    dry_run: bool,
    gitlab_project_id: str,
    gitlab_merge_request_id: int,
    comparison_sha: str,
    change_type_processing_mode: str,
    mr_management_enabled: bool = False,
) -> None:
    comparison_gql_api = gql.get_api_for_sha(
        comparison_sha, QONTRACT_INTEGRATION, validate_schemas=False
    )

    if change_type_processing_mode == CHANGE_TYPE_PROCESSING_MODE_LIMITED:
        logging.info(
            f"running in `{CHANGE_TYPE_PROCESSING_MODE_LIMITED}` mode that "
            f"prevents full self-service MR {gitlab_merge_request_id} contains "
            "changes other than datafiles, resources, docs or testdata"
        )
    elif change_type_processing_mode == CHANGE_TYPE_PROCESSING_MODE_AUTHORITATIVE:
        logging.info(
            f"running in `{CHANGE_TYPE_PROCESSING_MODE_AUTHORITATIVE}` mode "
            "that allows full self-service"
        )
    else:
        logging.info(
            f"running in unknown mode {change_type_processing_mode}. end "
            "processing. this integration is still in active development "
            "therefore it will not fail right now but exit(0) instead."
        )
        return

    file_diff_resolver = QontractServerFileDiffResolver(comparison_sha=comparison_sha)

    try:
        # fetch change-types from current bundle to verify they are syntactically correct.
        # this is a cheap way to figure out if a newly introduced change-type works.
        # needs a lot of improvements!
        fetch_change_type_processors(gql.get_api(), file_diff_resolver)
        # also verify that self service roles are configured correctly, e.g. if change-types
        # are brought together only with compatible schema files
        fetch_self_service_roles(gql.get_api())
    except Exception as e:
        logging.error(e)
        sys.exit(1)

    # get change types from the comparison bundle to prevent privilege escalation
    logging.info(
        f"fetching change types and permissions from comparison bundle "
        f"(sha={comparison_sha}, commit_id={comparison_gql_api.commit}, "
        f"build_time {comparison_gql_api.commit_timestamp_utc})"
    )
    change_type_processors = fetch_change_type_processors(
        comparison_gql_api, file_diff_resolver
    )

    # an error while trying to cover changes will not fail the integration
    # and the PR check - self service merges will not be available though
    try:
        #
        #   C H A N G E   C O V E R A G E
        #
        changes = fetch_bundle_changes(comparison_sha)
        logging.info(
            f"detected {len(changes)} changed files "
            f"with {sum(c.raw_diff_count() for c in changes)} differences "
            f"and {len([c for c in changes if c.metadata_only_change])} metadata-only changes"
        )
        cover_changes(
            changes,
            change_type_processors,
            comparison_gql_api,
        )
        self_serviceable = (
            len(changes) > 0
            and all(c.all_changes_covered() for c in changes)
            and change_type_processing_mode == CHANGE_TYPE_PROCESSING_MODE_AUTHORITATIVE
        )

        #
        #   D E C I S I O N S
        #

        with init_gitlab(gitlab_project_id) as gl:
            merge_request = gl.get_merge_request(gitlab_merge_request_id)

            comments = gl.get_merge_request_comments(merge_request)
            ok_to_test_approvers = {
                c.username for c in comments if c.body.strip() == "/ok-to-test"
            }

            change_admitted = is_change_admitted(
                changes,
                gl.get_merge_request_author_username(merge_request),
                ok_to_test_approvers,
            )
            approver_decisions = get_approver_decisions_from_mr_comments(
                gl.get_merge_request_comments(
                    merge_request,
                    include_description=True,
                    include_approvals=True,
                    approval_body=DecisionCommand.APPROVED.value,
                )
            )
            change_decisions = apply_decisions_to_changes(
                changes,
                approver_decisions,
                {
                    gl.user.username,
                    gl.get_merge_request_author_username(merge_request),
                },
            )
            hold = any(d.is_held() for d in change_decisions)
            approved = all(
                d.is_approved() and not d.is_held() for d in change_decisions
            )

            #
            #   R E P O R T I N G
            #

            if mr_management_enabled:
                write_coverage_report_to_mr(
                    self_serviceable,
                    change_decisions,
                    change_admitted,
                    change_type_processing_mode
                    == CHANGE_TYPE_PROCESSING_MODE_AUTHORITATIVE,
                    merge_request,
                    gl,
                )
            write_coverage_report_to_stdout(change_decisions)

            #
            #   L A B E L I N G
            #

            # base labels
            conditional_labels = {
                SELF_SERVICEABLE: self_serviceable,
                NOT_SELF_SERVICEABLE: not self_serviceable,
                HOLD: self_serviceable and hold,
                RESTRICTED: not change_admitted,
            }

            # priority labels
            mr_priority = get_priority_for_changes(changes)
            conditional_labels.update({
                prioritized_approval_label(p.value): self_serviceable
                and approved
                and p == mr_priority
                for p in ChangeTypePriority
            })
            labels = manage_conditional_label(
                current_labels=merge_request.labels,
                conditional_labels=conditional_labels,
                dry_run=False,
            )

            # change-owner labels
            labels = {
                co_label
                for co_label in labels
                if not co_label.startswith("change-owner/")
            }
            for bc in changes:
                labels.update(
                    change_owner_label(label) for label in bc.change_owner_labels
                )

            if mr_management_enabled:
                gl.set_labels_on_merge_request(merge_request, labels)
            elif SELF_SERVICEABLE in labels:
                # if MR management is disabled, we need to make sure the self-serviceable
                # labels is not present, because other integration react to them
                # e.g. gitlab-housekeeper rejects direct lgtm labels and the review-queue
                # skips MRs with this label
                gl.remove_label(merge_request, SELF_SERVICEABLE)

            if not change_admitted:
                raise NotAdmittedError("Change not admitted")

    except NotAdmittedError as e:
        # This is not an error, but we want to fail the integration, since the
        # MR author is not allowed to do this change
        logging.error(e)
        sys.exit(1)
    except BaseException:
        logging.error(traceback.format_exc())
