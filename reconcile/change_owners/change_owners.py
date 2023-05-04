import logging
import sys
import traceback
from collections import defaultdict

from reconcile import queries
from reconcile.change_owners.approver import GqlApproverResolver
from reconcile.change_owners.bundle import (
    BundleFileType,
    FileDiffResolver,
    QontractServerFileDiffResolver,
)
from reconcile.change_owners.change_types import (
    BundleFileChange,
    ChangeTypePriority,
    ChangeTypeProcessor,
    create_bundle_file_change,
    get_priority_for_changes,
    init_change_type_processors,
)
from reconcile.change_owners.decision import (
    ChangeDecision,
    DecisionCommand,
    apply_decisions_to_changes,
    get_approver_decisions_from_mr_comments,
)
from reconcile.change_owners.implicit_ownership import (
    cover_changes_with_implicit_ownership,
)
from reconcile.change_owners.self_service_roles import (
    cover_changes_with_self_service_roles,
)
from reconcile.gql_definitions.change_owners.queries import (
    change_types,
    self_service_roles,
)
from reconcile.gql_definitions.change_owners.queries.self_service_roles import RoleV1
from reconcile.utils import gql
from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.mr.labels import (
    HOLD,
    NOT_SELF_SERVICEABLE,
    SELF_SERVICEABLE,
    prioritized_approval_label,
)
from reconcile.utils.output import format_table
from reconcile.utils.semver_helper import make_semver

QONTRACT_INTEGRATION = "change-owners"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)


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


def validate_self_service_role(role: RoleV1) -> None:
    for ssc in role.self_service or []:
        if ssc.change_type.context_schema:
            # check that all referenced datafiles have a schema that
            # is compatible with the change-type
            incompatible_datafiles = [
                df.path
                for df in ssc.datafiles or []
                if df.datafile_schema != ssc.change_type.context_schema
            ]
            if incompatible_datafiles:
                raise ValueError(
                    f"The datafiles {incompatible_datafiles} are not compatible with the "
                    f"{ssc.change_type.name} change-types contextSchema {ssc.change_type.context_schema}"
                )


def fetch_self_service_roles(gql_api: gql.GqlApi) -> list[RoleV1]:
    roles: list[RoleV1] = []
    for r in self_service_roles.query(gql_api.query).roles or []:
        if not r.self_service:
            continue
        validate_self_service_role(r)
        roles.append(r)
    return roles


def fetch_change_type_processors(
    gql_api: gql.GqlApi, file_diff_resolver: FileDiffResolver
) -> list[ChangeTypeProcessor]:
    change_type_list = change_types.query(gql_api.query).change_types or []
    return list(
        init_change_type_processors(change_type_list, file_diff_resolver).values()
    )


def fetch_bundle_changes(comparison_sha: str) -> list[BundleFileChange]:
    """
    reaches out to the qontract-server diff endpoint to find the files that
    changed within two bundles (the current one representing the MR and the
    explicitely passed comparision bundle - usually the state of the master branch).
    """
    changes = gql.get_diff(comparison_sha)
    bundle_changes = _parse_bundle_changes(changes)
    try:
        return _aggregate_file_moves(bundle_changes)
    except Exception as e:
        logging.error(f"Failed to post process bundle changes: {e}")
        # if any post processing action fails, we want the raw bundle changes
        # to be reviewed
        return bundle_changes


def _aggregate_file_moves(
    bundle_changes: list[BundleFileChange],
) -> list[BundleFileChange]:
    """
    This function tries to detect file moves by looking at the bundle changes. If an
    add and remove file change with the same content is detected, those changes are
    replaced with a single move change where the only difference is the path.
    """
    move_candidates: dict[str, list[BundleFileChange]] = defaultdict(list)
    new_bundle_changes = []
    for c in bundle_changes:
        potential_move_sha = None
        if c.is_file_creation():
            potential_move_sha = c.new_content_sha()
        elif c.is_file_deletion():
            potential_move_sha = c.old_content_sha()
        if potential_move_sha:
            move_candidates[potential_move_sha].append(c)
        else:
            new_bundle_changes.append(c)

    for candidates in move_candidates.values():
        if len(candidates) == 2:
            # if there are two candidates, they could represent a file move.
            # lets check if that is the case
            deletion = (
                candidates[0] if candidates[0].is_file_deletion() else candidates[1]
            )
            addition = (
                candidates[0] if candidates[0].is_file_creation() else candidates[1]
            )
            if (
                deletion != addition
                and deletion.fileref.file_type == addition.fileref.file_type
                and deletion.fileref.path != addition.fileref.path
            ):
                # the candidates represent a file move. let's add a new
                # change that represents the move
                move_change = create_bundle_file_change(
                    deletion.fileref.path,
                    deletion.fileref.schema,
                    deletion.fileref.file_type,
                    deletion.old,
                    addition.new,
                )
                if move_change:
                    # move_change will always be present. this check is just to
                    # satisfy mypy
                    new_bundle_changes.append(move_change)
                    continue

        # the candidates turned out to be unrelated changes. lets add them back
        # to the list of changes
        new_bundle_changes.extend(candidates)
    return new_bundle_changes


def _parse_bundle_changes(bundle_changes) -> list[BundleFileChange]:
    """
    parses the output of the qontract-server /diff endpoint
    """
    datafiles = bundle_changes["datafiles"].values()
    resourcefiles = bundle_changes["resources"].values()
    logging.debug(
        f"bundle contains {len(datafiles)} changed datafiles and {len(resourcefiles)} changed resourcefiles"
    )

    change_list = []
    for c in datafiles:
        bc = create_bundle_file_change(
            path=c.get("datafilepath"),
            schema=c.get("datafileschema"),
            file_type=BundleFileType.DATAFILE,
            old_file_content=c.get("old"),
            new_file_content=c.get("new"),
        )
        if bc is not None:
            change_list.append(bc)
        else:
            logging.debug(
                f"skipping datafile {c.get('datafilepath')} - no changes detected"
            )

    for c in resourcefiles:
        bc = create_bundle_file_change(
            path=c.get("resourcepath"),
            schema=c.get("new", {}).get("$schema", c.get("old", {}).get("$schema")),
            file_type=BundleFileType.RESOURCEFILE,
            old_file_content=c.get("old", {}).get("content"),
            new_file_content=c.get("new", {}).get("content"),
        )
        if bc is not None:
            change_list.append(bc)
        else:
            logging.debug(
                f"skipping resourcefile {c.get('resourcepath')} - no changes detected"
            )

    return change_list


CHANGE_TYPE_PROCESSING_MODE_LIMITED = "limited"
CHANGE_TYPE_PROCESSING_MODE_AUTHORITATIVE = "authoritative"


def manage_conditional_label(
    current_labels: list[str],
    conditional_labels: dict[str, bool],
    dry_run: bool = True,
) -> list[str]:
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
    return new_labels


def write_coverage_report_to_mr(
    self_serviceable: bool,
    change_decisions: list[ChangeDecision],
    authoritative: bool,
    mr_id: int,
    gl: GitLabApi,
) -> None:
    """
    adds the change coverage report and decision summary as a comment
    to the merge request. this will delete the last report comment and add
    a new one.
    """
    change_coverage_report_header = "Change coverage report"
    # delete previous report comment
    gl.delete_merge_request_comments(mr_id, startswith=change_coverage_report_header)

    # add new report comment
    results = []
    approver_reachability = set()
    for d in change_decisions:
        approvers = [
            f"{ctctx.context} - { ' '.join([f'@{a.org_username}' if a.tag_on_merge_requests else a.org_username for a in ctctx.approvers]) }"
            for ctctx in d.deduped_coverage()
        ]
        for cctx in d.deduped_coverage():
            approver_reachability.update(
                {ar.render_for_mr_report() for ar in cctx.approver_reachability or []}
            )
        if not approvers:
            approvers = ["[- not self-serviceable -]"]
        item = {
            "file": d.file.path,
            "schema": d.file.schema,
            "change": d.diff.path,
        }
        if d.is_held():
            item["status"] = "hold"
        elif d.is_approved():
            item["status"] = "approved"
        item["approvers"] = approvers
        results.append(item)
    coverage_report = format_table(
        results, ["file", "change", "status", "approvers"], table_format="github"
    )

    self_serviceability_hint = "All changes require an `/lgtm` from a listed approver "
    if not self_serviceable:
        self_serviceability_hint += "but <b>not all changes are self-serviceable and require AppSRE approval</b>"
    if not authoritative:
        self_serviceability_hint += "\n\nchanges outside of data and resources detected - <b>PAY EXTRA ATTENTION WHILE REVIEWING</b>\n\n"
    approver_reachability_hint = "Reach out to approvers for reviews"
    if approver_reachability:
        approver_reachability_hint += " on\n" + "\n".join(
            [f"* {ar}" for ar in approver_reachability or []]
        )
    gl.add_comment_to_merge_request(
        mr_id,
        f"{change_coverage_report_header}<br/>"
        f"{self_serviceability_hint}\n"
        f"{coverage_report}\n\n"
        f"{approver_reachability_hint}\n\n"
        + f"Supported commands: {' '.join([f'`{d.value}`' for d in DecisionCommand])} ",
    )


def write_coverage_report_to_stdout(change_decisions: list[ChangeDecision]) -> None:
    results = []
    for d in change_decisions:
        if d.coverage:
            for ctx in d.coverage:
                results.append(
                    {
                        "file": d.file.path,
                        "schema": d.file.schema,
                        "changed path": d.diff.path,
                        "change type": ctx.change_type_processor.name,
                        "origin": ctx.origin,
                        "context": ctx.context,
                        "approver_reachability": ", ".join(
                            [
                                ar.render_for_mr_report()
                                for ar in ctx.approver_reachability or []
                            ]
                        ),
                        "disabled": str(ctx.disabled),
                    }
                )
        else:
            results.append(
                {
                    "file": d.file.path,
                    "schema": d.file.schema,
                    "changed path": d.diff.path,
                }
            )

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
            f"detected {len(changes)} changed files with {sum(c.raw_diff_count() for c in changes)} differences"
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

        gl = init_gitlab(gitlab_project_id)
        approver_decisions = get_approver_decisions_from_mr_comments(
            gl.get_merge_request_comments(
                gitlab_merge_request_id, include_description=True
            )
        )
        change_decisions = apply_decisions_to_changes(
            changes,
            approver_decisions,
            {
                gl.user.username,
                gl.get_merge_request_author_username(gitlab_merge_request_id),
            },
        )
        hold = any(d.is_held() for d in change_decisions)
        approved = all(d.is_approved() and not d.is_held() for d in change_decisions)

        #
        #   R E P O R T I N G
        #

        if mr_management_enabled:
            write_coverage_report_to_mr(
                self_serviceable,
                change_decisions,
                change_type_processing_mode
                == CHANGE_TYPE_PROCESSING_MODE_AUTHORITATIVE,
                gitlab_merge_request_id,
                gl,
            )
        write_coverage_report_to_stdout(change_decisions)

        #
        #   L A B E L I N G
        #

        labels = gl.get_merge_request_labels(gitlab_merge_request_id)

        # base labels
        conditional_labels = {
            SELF_SERVICEABLE: self_serviceable,
            NOT_SELF_SERVICEABLE: not self_serviceable,
            HOLD: self_serviceable and hold,
        }

        # priority labels
        mr_priority = get_priority_for_changes(changes)
        conditional_labels.update(
            {
                prioritized_approval_label(p.value): self_serviceable
                and approved
                and p == mr_priority
                for p in ChangeTypePriority
            }
        )
        labels = manage_conditional_label(
            current_labels=labels, conditional_labels=conditional_labels, dry_run=False
        )
        if mr_management_enabled:
            gl.set_labels_on_merge_request(gitlab_merge_request_id, labels)
        else:
            # if MR management is disabled, we need to make sure the self-serviceable
            # labels is not present, because other integration react to them
            # e.g. gitlab-housekeeper rejects direct lgtm labels and the review-queue
            # skips MRs with this label
            if SELF_SERVICEABLE in labels:
                gl.remove_label_from_merge_request(
                    gitlab_merge_request_id, SELF_SERVICEABLE
                )

    except BaseException:
        logging.error(traceback.format_exc())
