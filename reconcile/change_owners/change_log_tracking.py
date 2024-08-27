import logging
from collections.abc import Callable
from dataclasses import asdict, dataclass, field

from reconcile.change_owners.bundle import (
    NoOpFileDiffResolver,
    QontractServerDiff,
)
from reconcile.change_owners.change_owners import fetch_change_type_processors
from reconcile.change_owners.change_types import ChangeTypeContext
from reconcile.change_owners.changes import aggregate_file_moves, parse_bundle_changes
from reconcile.utils import gql
from reconcile.utils.defer import defer
from reconcile.utils.runtime.integration import NoParams, QontractReconcileIntegration
from reconcile.utils.semver_helper import make_semver
from reconcile.utils.state import init_state

BUNDLE_DIFFS_OBJ = "bundle-diffs.json"


@dataclass
class ChangeLogItem:
    commit: str
    change_types: list[str] = field(default_factory=list)
    error: bool = False


@dataclass
class ChangeLog:
    items: list[ChangeLogItem] = field(default_factory=list)


class ChangeLogIntegration(QontractReconcileIntegration[NoParams]):
    def __init__(self) -> None:
        super().__init__(NoParams())
        self.qontract_integration = "change-log-tracking"
        self.qontract_integration_version = make_semver(0, 1, 0)

    @property
    def name(self) -> str:
        return self.qontract_integration

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

        change_log = ChangeLog(**integration_state.get(BUNDLE_DIFFS_OBJ))
        for item in diff_state.ls():
            key = item.lstrip("/")
            commit = key.rstrip(".json")
            logging.info(f"Processing commit {commit}")
            change_log_item = ChangeLogItem(
                commit=commit,
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

        if not dry_run:
            integration_state.add(BUNDLE_DIFFS_OBJ, asdict(change_log), force=True)
