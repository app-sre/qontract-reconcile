import json
import logging
import os
from collections.abc import Callable
from dataclasses import asdict, dataclass, field

from reconcile.change_owners.bundle import (
    NoOpFileDiffResolver,
    QontractServerDiff,
)
from reconcile.change_owners.change_owners import fetch_change_type_processors
from reconcile.change_owners.change_types import ChangeTypeContext
from reconcile.change_owners.changes import aggregate_file_moves, parse_bundle_changes
from reconcile.typed_queries.apps import get_apps
from reconcile.typed_queries.get_state_aws_account import get_state_aws_account
from reconcile.utils import gql
from reconcile.utils.aws_api import AWSApi
from reconcile.utils.defer import defer
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
    change_types: list[str] = field(default_factory=list)
    error: bool = False
    apps: list[str] = field(default_factory=list)


@dataclass
class ChangeLog:
    items: list[ChangeLogItem] = field(default_factory=list)


class ChangeLogIntegrationParams(PydanticRunParams):
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
        state_bucket_name = os.environ["APP_INTERFACE_STATE_BUCKET"]
        state_bucket_account_name = os.environ["APP_INTERFACE_STATE_BUCKET_ACCOUNT"]

        change_type_processors = [
            ctp
            for ctp in fetch_change_type_processors(
                gql.get_api(), NoOpFileDiffResolver()
            )
            if ctp.labels and "change_log_tracking" in ctp.labels
        ]
        apps = get_apps()
        app_name_by_path = {a.path: a.name for a in apps}

        integration_state = init_state(
            integration=self.name,
        )
        if defer:
            defer(integration_state.cleanup)
        account = get_state_aws_account(state_bucket_account_name)
        if not account:
            raise ValueError("no state aws account found")
        aws_api = AWSApi(
            1,
            [account.dict(by_alias=True)],
            secret_reader=self.secret_reader,
            init_users=False,
        )
        if defer:
            defer(aws_api.cleanup)

        if not self.params.process_existing:
            existing_change_log = ChangeLog(**integration_state.get(BUNDLE_DIFFS_OBJ))
            existing_change_log_items = [
                ChangeLogItem(**i)  # type: ignore[arg-type]
                for i in existing_change_log.items
            ]
        change_log = ChangeLog()
        for key in aws_api.list_s3_objects(
            account.name,
            state_bucket_name,
            "bundle-archive/diff",
        ):
            commit = os.path.basename(key).rstrip(".json")
            if not self.params.process_existing:
                existing_change_log_item = next(
                    (i for i in existing_change_log_items if i.commit == commit), None
                )
                if existing_change_log_item:
                    logging.debug(f"Found existing commit {commit}")
                    change_log.items.append(existing_change_log_item)
                    continue

            logging.info(f"Processing commit {commit}")
            change_log_item = ChangeLogItem(
                commit=commit,
            )
            change_log.items.append(change_log_item)
            obj = aws_api.get_s3_object_content(account.name, state_bucket_name, key)
            if not obj:
                logging.error(f"Error processing commit {commit}")
                change_log_item.error = True
                continue
            diff = QontractServerDiff(**json.loads(obj))
            changes = aggregate_file_moves(parse_bundle_changes(diff))
            for change in changes:
                logging.debug(f"Processing change {change}")
                change_versions = filter(None, [change.old, change.new])
                match change.fileref.schema:
                    case "/app-sre/app-1.yml":
                        changed_apps = {c["name"] for c in change_versions}
                        change_log_item.apps.extend(changed_apps)
                    case "/app-sre/saas-file-2.yml" | "/openshift/namespace-1.yml":
                        changed_apps = {
                            name
                            for c in change_versions
                            if (name := app_name_by_path.get(c["app"]["$ref"]))
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

        if not dry_run:
            integration_state.add(BUNDLE_DIFFS_OBJ, asdict(change_log), force=True)
