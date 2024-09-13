import logging
from collections import defaultdict
from collections.abc import Callable
from dataclasses import asdict, dataclass, field

from reconcile.change_owners.bundle import (
    NoOpFileDiffResolver,
    QontractServerDiff,
)
from reconcile.change_owners.change_owners import (
    fetch_change_type_processors,
    init_gitlab,
)
from reconcile.change_owners.change_types import ChangeTypeContext
from reconcile.change_owners.changes import aggregate_file_moves, parse_bundle_changes
from reconcile.typed_queries.apps import get_apps
from reconcile.typed_queries.external_resources import get_namespaces
from reconcile.utils import gql
from reconcile.utils.defer import defer
from reconcile.utils.gitlab_api import MRState
from reconcile.utils.runtime.integration import (
    PydanticRunParams,
    QontractReconcileIntegration,
)
from reconcile.utils.state import init_state

QONTRACT_INTEGRATION = "change-log-tracking"
BUNDLE_DIFFS_OBJ = "bundle-diffs.json"


@dataclass
class ChangeLogItem:
    commit: str
    merged_at: str
    change_types: list[str] = field(default_factory=list)
    error: bool = False
    apps: list[str] = field(default_factory=list)


@dataclass
class ChangeLog:
    items: list[ChangeLogItem] = field(default_factory=list)


class ChangeLogIntegrationParams(PydanticRunParams):
    gitlab_project_id: str
    process_existing: bool = False


class ChangeLogIntegration(QontractReconcileIntegration[ChangeLogIntegrationParams]):
    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    @defer
    def run(
        self,
        dry_run: bool,
        defer: Callable | None = None,
    ) -> None:
        change_type_processors = [
            ctp
            for ctp in fetch_change_type_processors(
                gql.get_api(), NoOpFileDiffResolver()
            )
            if ctp.labels and "change_log_tracking" in ctp.labels
        ]
        apps = get_apps()
        app_name_by_path = {a.path: a.name for a in apps}
        namespaces = get_namespaces()
        app_names_by_cluster_name = defaultdict(set)
        for ns in namespaces:
            cluster = ns.cluster.name
            app = ns.app.name
            app_names_by_cluster_name[cluster].add(app)

        integration_state = init_state(
            integration=self.name,
        )
        if defer:
            defer(integration_state.cleanup)
        diff_state = init_state(
            integration=self.name,
        )
        if defer:
            defer(diff_state.cleanup)
        diff_state.state_path = "bundle-archive/diff"

        if not self.params.process_existing:
            existing_change_log = ChangeLog(**integration_state.get(BUNDLE_DIFFS_OBJ))
            existing_change_log_items = [
                ChangeLogItem(**i)  # type: ignore[arg-type]
                for i in existing_change_log.items
            ]
        gl = init_gitlab(self.params.gitlab_project_id)
        if defer:
            defer(gl.cleanup)
        change_log = ChangeLog()
        for item in diff_state.ls():
            key = item.lstrip("/")
            commit = key.rstrip(".json")
            if not self.params.process_existing:
                existing_change_log_item = next(
                    (i for i in existing_change_log_items if i.commit == commit), None
                )
                if existing_change_log_item:
                    logging.debug(f"Found existing commit {commit}")
                    change_log.items.append(existing_change_log_item)
                    continue

            logging.info(f"Processing commit {commit}")
            gl_commit = gl.project.commits.get(commit)
            merged_at = max(
                mr["merged_at"]
                for mr in gl_commit.merge_requests()
                if mr["state"] == MRState.MERGED
                and mr["target_branch"] == gl.project.default_branch
            )
            change_log_item = ChangeLogItem(
                commit=commit,
                merged_at=merged_at,
            )
            change_log.items.append(change_log_item)
            obj = diff_state.get(key, None)
            if not obj:
                logging.error(f"Error processing commit {commit}")
                change_log_item.error = True
                continue
            diff = QontractServerDiff(**obj)
            changes = aggregate_file_moves(parse_bundle_changes(diff))
            for change in changes:
                logging.debug(f"Processing change {change}")
                change_versions = filter(None, [change.old, change.new])
                match change.fileref.schema:
                    case "/app-sre/app-1.yml":
                        changed_apps = {c["name"] for c in change_versions}
                        change_log_item.apps.extend(changed_apps)
                    case (
                        "/app-sre/saas-file-2.yml"
                        | "/openshift/namespace-1.yml"
                        | "/dependencies/jenkins-config-1.yml"
                    ):
                        changed_apps = {
                            name
                            for c in change_versions
                            if (name := app_name_by_path.get(c["app"]["$ref"]))
                        }
                        change_log_item.apps.extend(changed_apps)
                    case "/openshift/cluster-1.yml":
                        changed_apps = {
                            name
                            for c in change_versions
                            for name in app_names_by_cluster_name.get(c["name"], [])
                        }
                        change_log_item.apps.extend(changed_apps)

                # TODO(maorfr): switch apps to set
                change_log_item.apps = list(set(change_log_item.apps))

                for ctp in change_type_processors:
                    logging.info(f"Processing change type {ctp.name}")
                    ctx = ChangeTypeContext(
                        change_type_processor=ctp,
                        context="",
                        origin="",
                        context_file=change.fileref,
                        approvers=[],
                    )
                    covered_diffs = change.cover_changes(ctx)
                    if covered_diffs:
                        if ctp.name not in change_log_item.change_types:
                            change_log_item.change_types.append(ctp.name)

                change_log_item.change_types.extend(
                    special_dir
                    for special_dir in ("docs", "hack")
                    if any(
                        path.startswith(special_dir)
                        for gl_diff in gl_commit.diff()
                        for path in (gl_diff["old_path"], gl_diff["new_path"])
                    )
                )

        change_log.items = sorted(
            change_log.items, key=lambda i: i.merged_at, reverse=True
        )
        if not dry_run:
            integration_state.add(BUNDLE_DIFFS_OBJ, asdict(change_log), force=True)
