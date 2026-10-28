from __future__ import annotations

import logging
import sys
import traceback
from typing import TYPE_CHECKING

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
    validate_self_service_roles,
)
from reconcile.gql_definitions.change_owners.queries import change_types
from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.utils import gql
from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.mr.labels import (
    HOLD,
    NOT_SELF_SERVICEABLE,
    PENDING_SELF_SERVICE_APPROVAL,
    RESTRICTED,
    SELF_SERVICEABLE,
    change_owner_label,
    prioritized_approval_label,
)
from reconcile.utils.output import format_table
from reconcile.utils.secret_reader import create_secret_reader
from reconcile.utils.semver_helper import make_semver

if TYPE_CHECKING:
    from collections.abc import Iterable
    from collections.abc import Set as AbstractSet

    from gitlab.v4.objects import ProjectMergeRequest

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


def rebuild_change_owner_labels(
    current_labels: AbstractSet[str],
    change_owner_labels: Iterable[str],
) -> set[str]:
    """
    Strips every "change-owner/"-prefixed label from `current_labels` and
    re-adds only the ones derived from `change_owner_labels`. Labels that
    must survive across change-owners runs (e.g.
    SHOW_SELF_SERVICEABLE_IN_REVIEW_QUEUE, set directly by other
    integrations) must not be created via change_owner_label() for this
    reason - see its definition in reconcile/utils/mr/labels.py.
    """
    labels = {
        co_label
        for co_label in current_labels
        if not co_label.startswith("change-owner/")
    }
    labels.update(change_owner_label(label) for label in change_owner_labels)
    return labels


def build_status_message(
    self_serviceable: bool,
    self_service_portion_approved: bool,
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

    if not self_service_portion_approved:
        return f"""## 📝 Self-Service Approval Needed First
This MR also touches changes that AppSRE will need to review, but AppSRE won't see it in their review queue until the self-serviceable changes below are approved first.

Get `/lgtm` approval from the listed approvers below for the self-serviceable changes.

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
    self_service_portion_approved: bool,
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
        self_service_portion_approved=self_service_portion_approved,
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
    vault_settings = get_app_interface_vault_settings()
    secret_reader = create_secret_reader(use_vault=vault_settings.vault)
    return GitLabApi(
        instance, project_id=gitlab_project_id, secret_reader=secret_reader
    )


def _active_coverage(
    coverage: Iterable[ChangeTypeContext],
) -> list[ChangeTypeContext]:
    """
    Non-disabled contexts covering a diff. _apply_decision_to_diff() ignores
    the approvers of a disabled change-type when applying decisions, so a
    diff covered only by disabled contexts can never be approved - it must
    not count as "covered" for this check either, the same way
    DiffCoverage.is_directly_covered() treats it.
    """
    return [ctx for ctx in coverage if not ctx.disabled]


def _is_unblockable_by_tenant_context(
    ctx: ChangeTypeContext, app_sre_usernames: AbstractSet[str]
) -> bool:
    """
    True if this single change-type context can never be satisfied by a
    tenant: either it has no approvers at all (e.g. a role whose only
    members lack an org_username - build_role_approvers() drops those
    silently, even though role validation only requires the role to have
    *some* users/bots/memberSources, not that any survive
    approver-building), or every approver is an AppSRE member.
    """
    return all(a.org_username in app_sre_usernames for a in ctx.approvers)


def _direct_coverage_satisfied(
    d: ChangeDecision, app_sre_usernames: AbstractSet[str]
) -> bool | None:
    """
    Resolves a decision's own direct (non-fragment) coverage, mirroring
    ChangeDecision.is_approved()'s own rule (any explicit approval, or all
    auto-approved) and is_held()'s rule (any hold blocks) across every
    active direct context - tenant and AppSRE alike. An AppSRE context's
    own explicit approval resolves mixed coverage exactly like a tenant's
    would, so symmetrically its own hold blocks it too; the author's own
    hold ("mr-author") always blocks regardless of coverage.

    Returns None - fully exempt, no opinion either way - only when there's
    no tenant-approvable direct coverage at all: no coverage, every active
    context is AppSRE-only, or the only coverage is disabled. That's the
    one case nothing here could ever be resolved by anyone but AppSRE, so
    there's nothing for this check to gate on.
    """
    if d.hold.get("mr-author", False):
        return False
    active_coverage = _active_coverage(d.coverage)
    tenant_coverage = [
        ctx
        for ctx in active_coverage
        if not _is_unblockable_by_tenant_context(ctx, app_sre_usernames)
    ]
    if not tenant_coverage:
        return None
    if any(d.hold.get(ctx.context, False) for ctx in active_coverage):
        return False
    contexts = {ctx.context for ctx in active_coverage}
    return any(d.approve.get(c, False) for c in contexts) or all(
        d.context_auto_approval.get(c, False) for c in contexts
    )


def _is_self_service_satisfied(
    d: ChangeDecision, app_sre_usernames: AbstractSet[str]
) -> bool:
    """
    True if this decision doesn't need (further) self-service approval:
    either it isn't blocking in the first place (no active coverage, or
    covered only by change-types no tenant could ever satisfy), or it's
    already approved and not held.

    For a diff split into fragments, each fragment is evaluated the same
    way independently, rather than relying on the parent's own
    is_approved()/is_held() - which aggregate across *every* context the
    parent carries, including any AppSRE-only ones that can't be approved
    until AppSRE can see the MR in the first place. The parent can also
    carry its own direct, tenant-approvable coverage added after the
    split (see _cover_changes_for_diffs() in changes.py, which doesn't
    propagate a newly covering context into existing fragments) - that
    coverage is evaluated independently of the fragments' own state, the
    same way it would be if it weren't fragment-covered at all.
    """
    if d.coverable_by_fragment_decisions:
        if _direct_coverage_satisfied(d, app_sre_usernames) is False:
            return False
        return all(
            _is_self_service_satisfied(fragment, app_sre_usernames)
            for fragment in d.fragment_decisions
        )
    return _direct_coverage_satisfied(d, app_sre_usernames) is not False


def is_self_service_portion_approved(
    change_decisions: Iterable[ChangeDecision],
    app_sre_usernames: AbstractSet[str],
) -> bool:
    """
    Checks whether every self-serviceable (covered) part of the MR has been
    approved and is not held. Changes that aren't blocking in the first
    place are ignored — see _is_self_service_satisfied() for the full list
    of cases (no coverage, AppSRE-only coverage, disabled coverage, and the
    same recursively for fragment-split diffs). Their approval, if any, is
    AppSRE's call via the NOT_SELF_SERVICEABLE/review-queue path, not this
    one. Vacuously True when there's nothing left to approve.
    """
    return all(
        _is_self_service_satisfied(d, app_sre_usernames) for d in change_decisions
    )


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
        validate_self_service_roles(gql.get_api())
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
            app_sre_usernames = {u.username for u in gl.get_app_sre_group_users()}

            comments = gl.get_merge_request_comments(merge_request)
            ok_to_test_approvers = {
                c.username for c in comments if c.body.strip() == "/ok-to-test"
            }

            mr_author = gl.get_merge_request_author_username(merge_request)
            change_admitted = is_change_admitted(
                changes,
                mr_author,
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
                    mr_author,
                },
                mr_author=mr_author,
            )
            hold = any(d.is_held() for d in change_decisions)
            approved = all(
                d.is_approved() and not d.is_held() for d in change_decisions
            )
            self_service_portion_approved = is_self_service_portion_approved(
                change_decisions, app_sre_usernames
            )

            #
            #   R E P O R T I N G
            #

            if mr_management_enabled:
                write_coverage_report_to_mr(
                    self_serviceable,
                    self_service_portion_approved,
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
                HOLD: hold,
                RESTRICTED: not change_admitted,
                PENDING_SELF_SERVICE_APPROVAL: (
                    not self_serviceable and not self_service_portion_approved
                ),
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
            labels = rebuild_change_owner_labels(
                labels,
                (label for bc in changes for label in bc.change_owner_labels),
            )

            if mr_management_enabled:
                gl.set_labels_on_merge_request(merge_request, labels)
            else:
                # if MR management is disabled, we need to make sure these
                # bot-managed labels are not left stale on the real MR when
                # their condition is no longer true, because other
                # integrations react to them, e.g. gitlab-housekeeping
                # rejects direct lgtm labels on self-serviceable MRs, and
                # the review queue skips MRs with PENDING_SELF_SERVICE_APPROVAL.
                # Check the condition directly against the MR's actual
                # current labels, not the locally computed `labels` set -
                # that set already reflects the desired (post-removal)
                # state, so checking it here would miss exactly the
                # transition (condition just turned false) this is meant
                # to clean up.
                if not self_serviceable and SELF_SERVICEABLE in merge_request.labels:
                    gl.remove_label(merge_request, SELF_SERVICEABLE)
                if (
                    self_serviceable or self_service_portion_approved
                ) and PENDING_SELF_SERVICE_APPROVAL in merge_request.labels:
                    gl.remove_label(merge_request, PENDING_SELF_SERVICE_APPROVAL)

            if not change_admitted:
                raise NotAdmittedError("Change not admitted")

    except NotAdmittedError as e:
        # This is not an error, but we want to fail the integration, since the
        # MR author is not allowed to do this change
        logging.error(e)
        sys.exit(1)
    except BaseException:
        logging.error(traceback.format_exc())
