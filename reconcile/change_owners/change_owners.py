from typing import Optional
import logging
import traceback

from reconcile.change_owners.decision import (
    DecisionCommand,
    ChangeDecision,
    get_approver_decisions_from_mr_comments,
    apply_decisions_to_changes,
)
from reconcile.utils.output import format_table
from reconcile.utils import gql
from reconcile.gql_definitions.change_owners.queries.self_service_roles import RoleV1
from reconcile.gql_definitions.change_owners.queries import (
    self_service_roles,
    change_types,
)
from reconcile.utils.semver_helper import make_semver

from reconcile.change_owners.change_types import (
    BundleFileChange,
    BundleFileType,
    ChangeTypeProcessor,
    create_bundle_file_change,
    build_change_type_processor,
)
from reconcile.change_owners.self_service_roles import (
    cover_changes_with_self_service_roles,
)

from reconcile.utils.gitlab_api import GitLabApi
from reconcile import queries

from reconcile.utils.mr.labels import (
    SELF_SERVICEABLE,
    NOT_SELF_SERVICEABLE,
    HOLD,
    APPROVED,
    AWAITING_APPROVAL,
)


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

    # ... add more cover_* functions to cover more changes based on dynamic
    # or static contexts. some ideas:
    # - users should be able to change certain things in their user file without
    #   explicit configuration in app-interface
    # - ...


def fetch_self_service_roles(gql_api: gql.GqlApi) -> list[RoleV1]:
    roles = self_service_roles.query(gql_api.query).roles or []
    return [r for r in roles if r.self_service]


def fetch_change_type_processors(gql_api: gql.GqlApi) -> list[ChangeTypeProcessor]:
    change_type_list = change_types.query(gql_api.query).change_types or []
    return [build_change_type_processor(ct) for ct in change_type_list]


def fetch_bundle_changes(comparison_sha: str) -> list[BundleFileChange]:
    """
    reaches out to the qontract-server diff endpoint to find the files that
    changed within two bundles (the current one representing the MR and the
    explicitely passed comparision bundle - usually the state of the master branch).
    """
    changes = gql.get_diff(comparison_sha)
    return _parse_bundle_changes(changes)


def _parse_bundle_changes(bundle_changes) -> list[BundleFileChange]:
    """
    parses the output of the qontract-server /diff endpoint
    """
    change_list = [
        create_bundle_file_change(
            path=c.get("datafilepath"),
            schema=c.get("datafileschema"),
            file_type=BundleFileType.DATAFILE,
            old_file_content=c.get("old"),
            new_file_content=c.get("new"),
        )
        for c in bundle_changes["datafiles"].values()
    ]
    change_list.extend(
        [
            create_bundle_file_change(
                path=c.get("resourcepath"),
                schema=c.get("new", {}).get("$schema", c.get("old", {}).get("$schema")),
                file_type=BundleFileType.RESOURCEFILE,
                old_file_content=c.get("old", {}).get("content"),
                new_file_content=c.get("new", {}).get("content"),
            )
            for c in bundle_changes["resources"].values()
        ]
    )
    # get rid of Nones - create_bundle_file_change returns None if no real change has been detected
    return [c for c in change_list if c]


CHANGE_TYPE_PROCESSING_MODE_LIMITED = "limited"
CHANGE_TYPE_PROCESSING_MODE_AUTHORATIVE = "authorative"


def manage_conditional_label(
    labels: list[str],
    condition: bool,
    true_label: Optional[str] = None,
    false_label: Optional[str] = None,
    dry_run: bool = True,
) -> list[str]:
    new_labels = labels.copy()
    if condition:
        if true_label and true_label not in labels:
            if not dry_run:
                new_labels.append(true_label)
            logging.info(f"adding label {true_label}")
        if false_label and false_label in labels:
            if not dry_run:
                new_labels.remove(false_label)
            logging.info(f"removing label {false_label}")
    else:
        if true_label and true_label in labels:
            if not dry_run:
                new_labels.remove(true_label)
            logging.info(f"removing label {true_label}")
        if false_label and false_label not in labels:
            if not dry_run:
                new_labels.append(false_label)
            logging.info(f"adding label {false_label}")
    return new_labels


def write_coverage_report_to_mr(
    change_decisions: list[ChangeDecision], mr_id: int, gl: GitLabApi
) -> None:
    """
    adds the change coverage report and decision summary as a comment
    to the merge request. this will delete the last report comment and add
    a new one.
    """
    change_coverage_report_header = "Change coverage report"
    comments = gl.get_merge_request_comments(mr_id, include_description=True)
    # delete previous report comment
    for c in sorted(comments, key=lambda k: k["created_at"]):
        if c["username"] == gl.user.username and c["body"].startswith(
            change_coverage_report_header
        ):
            gl.delete_gitlab_comment(mr_id, c["id"])

    # add new report comment
    results = []
    for d in change_decisions:
        approvers = [
            f"{ctctx.context} - { ' '.join([f'@{a.org_username}' if a.tag_on_merge_requests else a.org_username for a in ctctx.approvers]) }"
            for ctctx in d.coverage
        ]
        if not approvers:
            approvers = ["not self-serviceable"]
        item = {
            "file": d.file.path,
            "schema": d.file.schema,
            "change": d.diff.path,
        }
        if d.decision.hold:
            item["status"] = "hold"
        elif d.decision.approve:
            item["status"] = "approved"
        item["approvers"] = approvers
        results.append(item)
    coverage_report = format_table(
        results, ["file", "change", "status", "approvers"], table_format="github"
    )
    gl.add_comment_to_merge_request(
        mr_id,
        f"{change_coverage_report_header}<br/> "
        "All changes require an `/lgtm` from a listed approver\n"
        f"{coverage_report}\n\n"
        f"Supported commands: {' '.join([f'`{d.value}`' for d in DecisionCommand])} ",
    )


def write_coverage_report_to_stdout(change_decisions: list[ChangeDecision]) -> None:
    results = []
    for d in change_decisions:
        item = {
            "file": d.file.path,
            "schema": d.file.schema,
            "changed path": d.diff.path,
        }
        if str(d.diff.path) != "$":
            item.update(
                {
                    "old value": d.diff.old_value_repr(),
                    "new value": d.diff.new_value_repr(),
                }
            )
        if d.decision.hold:
            item["status"] = "hold"
        elif d.decision.approve:
            item["status"] = "approved"
        if d.coverage:
            item.update(
                {
                    "change type": d.coverage[0].change_type_processor.change_type.name,
                    "context": d.coverage[0].context,
                    "approvers": ", ".join(
                        [a.org_username for a in d.coverage[0].approvers]
                    )[:20],
                }
            )
        results.append(item)

    print(
        format_table(
            results,
            [
                "file",
                "changed path",
                "old value",
                "new value",
                "change type",
                "context",
                "approvers",
                "status",
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
    elif change_type_processing_mode == CHANGE_TYPE_PROCESSING_MODE_AUTHORATIVE:
        logging.info(
            f"running in `{CHANGE_TYPE_PROCESSING_MODE_AUTHORATIVE}` mode "
            "that allows full self-service"
        )
    else:
        logging.info(
            f"running in unknown mode {change_type_processing_mode}. end "
            "processing. this integration is still in active development "
            "therefore it will not fail right now but exit(0) instead."
        )
        return

    # fetch change-types from current bundle to verify they are syntactically correct.
    # this is a cheap way to figure out if a newly introduced change-type works.
    # needs a lot of improvements!
    fetch_change_type_processors(gql.get_api())

    gl = init_gitlab(gitlab_project_id)
    mr = gl.get_merge_request(gitlab_merge_request_id)

    # skip processing if the MR is not in open state
    if mr.state != "opened":
        logging.info(
            f"skip processing of MR {gitlab_merge_request_id} in "
            f"{gl.project.name} because it is '{mr.state}'"
        )
        return

    # skip processing if the MR has been opened by the app-interface bot
    if mr.author.get("username") == gl.user.username:
        logging.info(
            f"skip processing of MR {gitlab_merge_request_id} in "
            f"{gl.project.name} as it has been opened by {gl.user.username}"
        )
        return

    # get change types from the comparison bundle to prevent privilege escalation
    logging.info(
        f"fetching change types and permissions from comparison bundle "
        f"(sha={comparison_sha}, commit_id={comparison_gql_api.commit}, "
        f"build_time {comparison_gql_api.commit_timestamp_utc})"
    )
    change_type_processors = fetch_change_type_processors(comparison_gql_api)

    # an error while trying to cover changes will not fail the integration
    # and the PR check - self service merges will not be available though
    try:
        #
        #   C H A N G E   C O V E R A G E
        #
        changes = fetch_bundle_changes(comparison_sha)
        cover_changes(
            changes,
            change_type_processors,
            comparison_gql_api,
        )

        self_servicable = (
            all(c.all_changes_covered() for c in changes)
            and change_type_processing_mode == CHANGE_TYPE_PROCESSING_MODE_AUTHORATIVE
        )

        # todo(goberlec) - what do we do if there are no changes?
        # do we want to add the bot/approved label and be done with it?

        #
        #   D E C I S I O N S
        #

        approver_decisions = get_approver_decisions_from_mr_comments(
            gl.get_merge_request_comments(
                gitlab_merge_request_id, include_description=True
            )
        )
        change_decisions = apply_decisions_to_changes(changes, approver_decisions)
        hold = any(d.decision.hold for d in change_decisions)
        approved = all(
            d.decision.approve and not d.decision.hold for d in change_decisions
        )

        #
        #   R E P O R T I N G
        #

        if mr_management_enabled:
            write_coverage_report_to_mr(change_decisions, gitlab_merge_request_id, gl)
        write_coverage_report_to_stdout(change_decisions)

        #
        #   L A B E L I N G
        #

        labels = gl.get_merge_request_labels(gitlab_merge_request_id)

        # for current testing purposes, the self servability label wills be managed
        # also when MR management is not enabled. this way change-owners can run next
        # to saas-file-owners and we can observe if bot integrations would consider
        # a saas-file only MR
        labels = manage_conditional_label(
            labels=labels,
            condition=self_servicable,
            true_label=SELF_SERVICEABLE,
            false_label=NOT_SELF_SERVICEABLE,
            dry_run=False,
        )
        labels = manage_conditional_label(
            labels=labels,
            condition=self_servicable and hold,
            true_label=HOLD,
            dry_run=not mr_management_enabled,
        )
        labels = manage_conditional_label(
            labels=labels,
            condition=self_servicable and approved,
            true_label=APPROVED,
            dry_run=not mr_management_enabled,
        )
        labels = manage_conditional_label(
            labels=labels,
            condition=self_servicable and not approved,
            true_label=AWAITING_APPROVAL,
            dry_run=not mr_management_enabled,
        )
        gl.set_labels_on_merge_request(gitlab_merge_request_id, labels)

    except BaseException:
        logging.error(traceback.format_exc())
