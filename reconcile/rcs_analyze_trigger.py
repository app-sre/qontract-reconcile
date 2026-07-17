from __future__ import annotations

import json
import logging
import sys
from operator import attrgetter
from typing import TYPE_CHECKING, Any

from kubernetes.client import (
    V1Container,
    V1EnvVar,
    V1JobSpec,
    V1LocalObjectReference,
    V1ObjectMeta,
    V1PodSpec,
    V1PodTemplateSpec,
    V1ResourceRequirements,
)
from pydantic import BaseModel

from reconcile import queries
from reconcile.change_owners.bundle import (
    BundleFileType,
    QontractServerFileDiffResolver,
)
from reconcile.change_owners.change_owners import (
    cover_changes,
    fetch_change_type_processors,
)
from reconcile.change_owners.changes import fetch_bundle_changes
from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.typed_queries.saas_files import SaasFileList
from reconcile.utils import gql
from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.jobcontroller.controller import (
    JobConcurrencyPolicy,
    JobStatus,
    build_job_controller,
)
from reconcile.utils.jobcontroller.models import K8sJob
from reconcile.utils.saas_diff import State, collect_state, find_ref_diffs
from reconcile.utils.secret_reader import create_secret_reader
from reconcile.utils.semver_helper import make_semver

if TYPE_CHECKING:
    from collections.abc import Iterable

    from gitlab.v4.objects import ProjectMergeRequestNote

    from reconcile.change_owners.bundle import FileRef
    from reconcile.utils.gitlab_api import Comment

LOG = logging.getLogger(__name__)

QONTRACT_INTEGRATION = "rcs-analyze-trigger"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)

# Exact-match trigger comment. RCS itself parses "/rcs note ..." and
# "/rcs override ..." on the same MR - those are not our concern and are
# never matched by this exact comparison.
TRIGGER_COMMAND = "/rcs analyze"

# Awarded to the trigger comment itself. This is the durable record of
# whether a comment already launched (or finished) an analysis - it never
# expires and needs no separate storage.
EMOJI_LAUNCHED = "eyes"
EMOJI_COMPLETED = "white_check_mark"

JOB_CHECK_INTERVAL_SECONDS = 30
JOB_TIMEOUT_SECONDS = 1800

# RCS is a thin client that mostly calls the GitLab/GitHub/Vertex AI APIs and
# waits on network I/O rather than doing heavy local computation, so these
# are deliberately modest. Tune if real usage shows otherwise.
JOB_CPU_REQUEST = "100m"
JOB_CPU_LIMIT = "500m"
JOB_MEMORY_REQUEST = "256Mi"
JOB_MEMORY_LIMIT = "512Mi"


class ComponentDiff(BaseModel):
    repo_url: str
    old_ref: str
    new_ref: str


def find_trigger_comment(comments: Iterable[Comment]) -> Comment | None:
    """
    Return the most recent comment matching the exact trigger line, or None
    if the trigger was never posted.
    """
    matches = []
    for c in comments:
        for line in c.body.split("\n") if c.body else []:
            if line.strip() == TRIGGER_COMMAND:
                matches.append(c)
                break
    if not matches:
        return None
    return max(matches, key=attrgetter("created_at"))


def _has_award_emoji(note: ProjectMergeRequestNote, emoji_name: str) -> bool:
    return any(e.name == emoji_name for e in note.awardemojis.list(iterator=True))


def _award_emoji(note: ProjectMergeRequestNote, emoji_name: str) -> None:
    note.awardemojis.create({"name": emoji_name})


def _repo_relative_path(file_ref: FileRef) -> str:
    """
    Bundle-relative paths (FileRef.path, e.g. "/services/foo/app.yml") map
    1:1 onto app-interface's git repo layout by prepending "data/" for
    datafiles or "resources/" for resourcefiles - the same root directories
    the bundle itself is built from. Reconstructing the real repo path lets
    us exact-match against GitLab's changed_paths instead of using a
    suffix-match (endswith) that could accidentally match an unrelated file
    whose bundle path happens to be a trailing substring of another path.
    """
    root = "data" if file_ref.file_type == BundleFileType.DATAFILE else "resources"
    return f"{root}/{file_ref.path.lstrip('/')}"


def is_authorized_approver(
    username: str,
    comparison_gql_api: gql.GqlApi,
    comparison_sha: str,
    changed_paths: Iterable[str],
) -> bool:
    """
    True if `username` is an authorized approver of every diff of every
    changed bundle file relevant to changed_paths, using the same
    change-type/self-service-role coverage machinery reconcile.change_owners
    uses to decide who may /lgtm or /hold an MR. Requiring coverage of every
    diff (not just one, and not just one file out of a batch) matches
    /lgtm's own all-diffs-covered bar (BundleFileChange.all_changes_covered),
    so a batched MR touching multiple components - or a single file with
    multiple independently-owned fields - can't be triggered by someone who
    only approves part of it.

    Unlike a real /lgtm admission, which different approvers can jointly
    satisfy across diffs, this requires the single commenting `username` to
    cover everything - there's no multi-comment approval history to draw
    from for a one-shot trigger.
    """
    file_diff_resolver = QontractServerFileDiffResolver(comparison_sha=comparison_sha)
    change_type_processors = fetch_change_type_processors(
        comparison_gql_api, file_diff_resolver
    )
    changes = fetch_bundle_changes(comparison_sha)
    cover_changes(changes, change_type_processors, comparison_gql_api)

    changed_paths_set = set(changed_paths)
    relevant_changes = [
        bc for bc in changes if _repo_relative_path(bc.fileref) in changed_paths_set
    ]
    if not relevant_changes:
        return False

    for bc in relevant_changes:
        if not bc.diff_coverage:
            return False
        for dc in bc.diff_coverage:
            if not any(
                ctx.includes_approver(username)
                for ctx in dc.coverage
                if not ctx.disabled
            ):
                return False
    return True


def collect_component_diffs(
    current_state: Iterable[State],
    desired_state: Iterable[State],
    changed_paths: Iterable[str],
) -> list[ComponentDiff]:
    """
    Compute per-component (repo_url, old_ref, new_ref) diffs for the
    promotion batch, using the shared ref-matching logic in
    reconcile.utils.saas_diff.find_ref_diffs (also used by
    openshift_saas_deploy_change_tester.collect_compare_diffs).
    """
    diffs = {
        (d.url, c.ref, d.ref)
        for d, c in find_ref_diffs(current_state, desired_state, changed_paths)
    }
    return [
        ComponentDiff(repo_url=repo_url, old_ref=old_ref, new_ref=new_ref)
        for repo_url, old_ref, new_ref in sorted(diffs)
    ]


class RcsAnalyzeJob(K8sJob, BaseModel, frozen=True):
    """
    Wraps a single release-confidence-score (RCS) analysis run into a
    Kubernetes Job. RCS reads the diffs and posts its own report comment on
    the MR using its own GitLab token - this job only runs the container and
    is not responsible for relaying any result.
    """

    gitlab_project_id: str
    gitlab_merge_request_iid: str
    trigger_comment_id: int
    triggered_by: str
    triggered_at: str
    diffs: list[ComponentDiff]
    rcs_job_image: str
    rcs_secrets: dict[str, str]

    def name_prefix(self) -> str:
        return "rcs-analyze"

    def unit_of_work_identity(self) -> Any:
        # Keying on the specific triggering comment (not the MR's head sha)
        # means each /rcs analyze comment causes exactly one job, regardless
        # of how many times pr_check reruns or how many more commits get
        # pushed to the MR afterwards. A rerun requires a genuinely new
        # comment.
        return (
            self.gitlab_project_id,
            self.gitlab_merge_request_iid,
            self.trigger_comment_id,
        )

    def secret_data(self) -> dict[str, str]:
        return self.rcs_secrets

    def job_spec(self) -> V1JobSpec:
        container = V1Container(
            name="rcs-analyze",
            image=self.rcs_job_image,
            image_pull_policy="Always",
            resources=V1ResourceRequirements(
                requests={"cpu": JOB_CPU_REQUEST, "memory": JOB_MEMORY_REQUEST},
                limits={"cpu": JOB_CPU_LIMIT, "memory": JOB_MEMORY_LIMIT},
            ),
            env=[
                V1EnvVar(
                    name="RCS_APP_INTERFACE_PROJECT_ID",
                    value=self.gitlab_project_id,
                ),
                V1EnvVar(
                    name="RCS_APP_INTERFACE_MR_IID",
                    value=self.gitlab_merge_request_iid,
                ),
                V1EnvVar(
                    name="RCS_COMPONENT_DIFFS",
                    value=json.dumps([d.model_dump() for d in self.diffs]),
                ),
                V1EnvVar(
                    name="RCS_TRIGGERED_BY",
                    value=self.triggered_by,
                ),
                V1EnvVar(
                    name="RCS_TRIGGERED_AT",
                    value=self.triggered_at,
                ),
                V1EnvVar(
                    name="RCS_TRIGGER_COMMENT_ID",
                    value=str(self.trigger_comment_id),
                ),
                *self.secret_data_to_env_vars_secret_refs(),
            ],
        )
        return V1JobSpec(
            backoff_limit=0,
            # Bounds the pod's wall-clock runtime so a hung RCS container
            # (e.g. stalled on an LLM API call) can't run in the cluster
            # indefinitely, independent of whether run()'s own wait times out.
            active_deadline_seconds=JOB_TIMEOUT_SECONDS,
            ttl_seconds_after_finished=3600,
            template=V1PodTemplateSpec(
                metadata=V1ObjectMeta(
                    annotations=self.annotations(), labels=self.labels()
                ),
                spec=V1PodSpec(
                    containers=[container],
                    image_pull_secrets=[V1LocalObjectReference(name="quay.io")],
                    restart_policy="Never",
                ),
            ),
        )


def run(
    dry_run: bool,
    gitlab_project_id: str,
    gitlab_merge_request_id: str,
    comparison_sha: str,
    job_controller_cluster: str,
    job_controller_namespace: str,
    rcs_job_image: str,
    rcs_secrets_path: str,
) -> None:
    try:
        _run(
            dry_run,
            gitlab_project_id,
            gitlab_merge_request_id,
            comparison_sha,
            job_controller_cluster,
            job_controller_namespace,
            rcs_job_image,
            rcs_secrets_path,
        )
    except Exception:
        # RCS is a manual, non-blocking, best-effort trigger: no unexpected
        # failure anywhere in this flow (GitLab/GQL access, Vault reads,
        # controller construction, job execution) may fail the calling
        # pr_check pipeline.
        LOG.exception(
            "Unexpected failure while processing %s trigger for MR !%s",
            TRIGGER_COMMAND,
            gitlab_merge_request_id,
        )


def _run(
    dry_run: bool,
    gitlab_project_id: str,
    gitlab_merge_request_id: str,
    comparison_sha: str,
    job_controller_cluster: str,
    job_controller_namespace: str,
    rcs_job_image: str,
    rcs_secrets_path: str,
) -> None:
    instance = queries.get_gitlab_instance()
    vault_settings = get_app_interface_vault_settings()
    secret_reader = create_secret_reader(use_vault=vault_settings.vault)

    with GitLabApi(
        instance, project_id=gitlab_project_id, secret_reader=secret_reader
    ) as gl:
        merge_request = gl.get_merge_request(gitlab_merge_request_id)
        comments = gl.get_merge_request_comments(merge_request)

        trigger_comment = find_trigger_comment(comments)
        if trigger_comment is None or trigger_comment.note is None:
            return
        note = trigger_comment.note

        if _has_award_emoji(note, EMOJI_LAUNCHED):
            # Already launched (regardless of outcome) by a prior pr_check
            # run for this exact comment.
            return

        changed_paths = gl.get_merge_request_changed_paths(merge_request)
        comparison_gql_api = gql.get_api_for_sha(
            comparison_sha, QONTRACT_INTEGRATION, validate_schemas=False
        )

        # Compute diffs before authorizing: it's cheaper (two SaasFileList
        # queries vs. a full bundle diff plus change-type/role resolution),
        # so the common "nothing relevant actually changed" case bails out
        # without paying for the expensive authorization pass at all.
        comparison_state = collect_state(
            SaasFileList(query_func=comparison_gql_api.query).saas_files
        )
        desired_state = collect_state(SaasFileList().saas_files)
        diffs = collect_component_diffs(comparison_state, desired_state, changed_paths)

        if not diffs:
            LOG.info(
                "%s triggered by %s on MR !%s but no component ref changes were found",
                TRIGGER_COMMAND,
                trigger_comment.username,
                gitlab_merge_request_id,
            )
            return

        try:
            authorized = is_authorized_approver(
                trigger_comment.username,
                comparison_gql_api,
                comparison_sha,
                changed_paths,
            )
        except BaseException:
            # Fail-soft: a misconfigured change-type/role elsewhere in the
            # bundle, unrelated to this MR, must not crash the pr_check.
            # BaseException (not Exception) to match change_owners.py's own
            # handling of this same cover_changes() call - scoped to just
            # this call so it can't swallow unrelated exceptions.
            LOG.exception(
                "Failed to resolve approvers for MR !%s - ignoring %s trigger",
                gitlab_merge_request_id,
                TRIGGER_COMMAND,
            )
            return

        if not authorized:
            LOG.warning(
                "%s triggered by %s on MR !%s, but they are not an "
                "authorized approver of the changed paths - ignoring",
                TRIGGER_COMMAND,
                trigger_comment.username,
                gitlab_merge_request_id,
            )
            return

        # Log the plan identically in both modes; dry_run is only checked
        # right at the execution point below, since (unlike its name
        # suggests) build_job_controller's dry_run flag is not actually
        # enforced anywhere in K8sJobController - we cannot rely on it to
        # skip the real job launch, so we must never reach that call at all
        # when dry_run is set.
        LOG.info(
            "Triggering RCS analysis for MR !%s (requested by %s) with %d "
            "component diff(s)",
            gitlab_merge_request_id,
            trigger_comment.username,
            len(diffs),
        )
        if dry_run:
            return

        rcs_secrets = secret_reader.read_all({"path": rcs_secrets_path})
        job = RcsAnalyzeJob(
            gitlab_project_id=gitlab_project_id,
            gitlab_merge_request_iid=str(gitlab_merge_request_id),
            trigger_comment_id=trigger_comment.id,
            triggered_by=trigger_comment.username,
            triggered_at=trigger_comment.created_at,
            diffs=diffs,
            rcs_job_image=rcs_job_image,
            rcs_secrets=rcs_secrets,
        )

        controller = build_job_controller(
            integration=QONTRACT_INTEGRATION,
            integration_version=QONTRACT_INTEGRATION_VERSION,
            cluster=job_controller_cluster,
            namespace=job_controller_namespace,
            secret_reader=secret_reader,
            dry_run=dry_run,
        )

        try:
            controller.enqueue_job(
                job, concurrency_policy=JobConcurrencyPolicy.NO_REPLACE
            )
            _award_emoji(note, EMOJI_LAUNCHED)
            status = (
                JobStatus.SUCCESS
                if controller.wait_for_job_completion(
                    job.name(),
                    check_interval_seconds=JOB_CHECK_INTERVAL_SECONDS,
                    timeout_seconds=JOB_TIMEOUT_SECONDS,
                )
                else JobStatus.ERROR
            )
            _award_emoji(note, EMOJI_COMPLETED)
        except TimeoutError:
            LOG.warning(
                "Timed out waiting for RCS analysis job to complete for MR "
                "!%s, deleting it",
                gitlab_merge_request_id,
            )
            try:
                controller.delete_job(job.name())
            except Exception:
                LOG.exception(
                    "Failed to delete timed-out RCS analysis job for MR !%s",
                    gitlab_merge_request_id,
                )
            return
        except Exception:
            # RCS is a manual, non-blocking, best-effort trigger: any
            # failure launching/monitoring it (e.g. a transient job-uid
            # lookup error in the controller) must not fail the calling
            # pr_check pipeline.
            LOG.exception(
                "Failed to launch or monitor RCS analysis job for MR !%s",
                gitlab_merge_request_id,
            )
            return

        if status != JobStatus.SUCCESS:
            LOG.warning(
                "RCS analysis job did not succeed (status=%s) for MR !%s",
                status,
                gitlab_merge_request_id,
            )
            try:
                controller.get_job_logs(job.name(), output=sys.stdout)
            except Exception:
                LOG.exception(
                    "Failed to retrieve logs for RCS analysis job for MR !%s",
                    gitlab_merge_request_id,
                )
