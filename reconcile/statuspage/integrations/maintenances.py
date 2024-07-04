import logging
import sys
from datetime import UTC, datetime, timedelta

from reconcile.slack_base import slackapi_from_queries
from reconcile.statuspage.atlassian import AtlassianStatusPageProvider
from reconcile.statuspage.integration import get_binding_state, get_status_pages
from reconcile.statuspage.page import StatusMaintenance
from reconcile.statuspage.state import S3ComponentBindingState
from reconcile.utils.differ import diff_iterables
from reconcile.utils.runtime.integration import (
    NoParams,
    QontractReconcileIntegration,
)
from reconcile.utils.semver_helper import make_semver

QONTRACT_INTEGRATION = "status-page-maintenances"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)


class StatusPageMaintenancesIntegration(QontractReconcileIntegration[NoParams]):
    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    def reconcile(
        self,
        dry_run: bool,
        desired_state: list[StatusMaintenance],
        current_state: list[StatusMaintenance],
        provider: AtlassianStatusPageProvider,
    ) -> None:
        diff = diff_iterables(
            current=current_state, desired=desired_state, key=lambda x: x.name
        )
        for a in diff.add.values():
            logging.info(f"Create StatusPage Maintenance: {a.name}")
            if not dry_run:
                provider.create_maintenance(a)
        for c in diff.change.values():
            raise NotImplementedError(
                f"Update StatusPage Maintenance is not supported at this time: {c.desired.name}"
            )
        for d in diff.delete.values():
            raise NotImplementedError(
                f"Delete StatusPage Maintenance is not supported at this time: {d.name}"
            )

    def notify(
        self,
        dry_run: bool,
        desired_state: list[StatusMaintenance],
        binding_state: S3ComponentBindingState,
    ) -> None:
        now = datetime.now(UTC)
        slack = slackapi_from_queries(QONTRACT_INTEGRATION, init_usergroups=False)
        for m in desired_state:
            scheduled_start = m.schedule_start
            if now <= scheduled_start <= now + timedelta(hours=1):
                state_key = f"notifications/{m.name}"
                if binding_state.state.exists(state_key):
                    continue
                logging.info(f"Notify StatusPage Maintenance: {m.name}")
                if not dry_run:
                    slack.chat_post_message(m.message)
                    binding_state.state.add(f"notifications/{m.name}")

    def run(self, dry_run: bool = False) -> None:
        binding_state = get_binding_state(self.name, self.secret_reader)
        pages = get_status_pages()
        now = datetime.now(UTC)

        error = False
        for p in pages:
            try:
                desired_state = [
                    StatusMaintenance.init_from_maintenance(
                        m, page_components=p.components or []
                    )
                    for m in p.maintenances or []
                    if datetime.fromisoformat(m.scheduled_start) > now
                ]
                page_provider = AtlassianStatusPageProvider.init_from_page(
                    page=p,
                    token=self.secret_reader.read_secret(p.credentials),
                    component_binding_state=binding_state,
                )
                current_state = [
                    m
                    for m in page_provider.scheduled_maintenances
                    if page_provider.has_component_binding_for(m.name)
                ]
                self.reconcile(
                    dry_run=dry_run,
                    desired_state=desired_state,
                    current_state=current_state,
                    provider=page_provider,
                )
                self.notify(
                    dry_run=dry_run,
                    desired_state=desired_state,
                    binding_state=binding_state,
                )
            except Exception:
                logging.exception(f"failed to reconcile statuspage {p.name}")
                error = True

        if error:
            sys.exit(1)
