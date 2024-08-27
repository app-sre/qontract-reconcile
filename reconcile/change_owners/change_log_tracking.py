import logging
from dataclasses import asdict, dataclass, field

from reconcile.change_owners.bundle import (
    NoOpFileDiffResolver,
    QontractServerDiff,
)
from reconcile.change_owners.change_owners import fetch_change_type_processors
from reconcile.change_owners.change_types import ChangeTypeContext
from reconcile.change_owners.changes import aggregate_file_moves, parse_bundle_changes
from reconcile.utils import gql
from reconcile.utils.runtime.integration import NoParams, QontractReconcileIntegration
from reconcile.utils.semver_helper import make_semver
from reconcile.utils.state import init_state


@dataclass
class ChangeLogItem:
    commit: str
    change_types: set[str] = field(default_factory=set)


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

    def run(self, dry_run: bool) -> None:
        change_type_processors = [
            ctp
            for ctp in fetch_change_type_processors(
                gql.get_api(), NoOpFileDiffResolver()
            )
            if ctp.labels and "change_log_tracking" in ctp.labels
        ]
        state = init_state(
            integration=self.name,
        )
        int_state_path = state.state_path
        state.state_path = "bundle-archive/diff"
        change_log = ChangeLog()
        for item in state.ls():
            key = item.lstrip("/")
            commit = key.rstrip(".json")
            logging.info(f"Processing commit {commit}")
            change_log_item = ChangeLogItem(
                commit=commit,
            )
            change_log.items.append(change_log_item)
            obj = state.get(key, None)
            if not obj:
                logging.error(f"Error processing commit {commit}")
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
                        change_log_item.change_types.add(ctp.name)

        state.state_path = int_state_path
        if not dry_run:
            state.add("bundle-diffs.json", asdict(change_log), force=True)
