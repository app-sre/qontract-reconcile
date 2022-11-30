import logging
import sys

from reconcile import queries
from reconcile.utils.semver_helper import make_semver
from reconcile.utils.state import State
from reconcile.utils.statuspage import atlassian
from reconcile.utils.statuspage.models import (
    StatusPage,
    register_provider,
)

QONTRACT_INTEGRATION = "status-page-components"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)


LOG = logging.getLogger(__name__)


def fetch_pages() -> list[StatusPage]:
    return [StatusPage(**p) for p in queries.get_status_pages()]


def get_state() -> State:
    settings = queries.get_app_interface_settings()
    accounts = queries.get_state_aws_accounts()
    return State(integration=QONTRACT_INTEGRATION, accounts=accounts, settings=settings)


def run(dry_run: bool = False):
    register_providers()
    state = get_state()
    status_pages = fetch_pages()

    error = False
    for page in status_pages:
        try:
            page.reconcile(dry_run, state)
        except Exception:
            LOG.exception(f"failed to reconcile statuspage {page.name}")
            error = True

    if error:
        sys.exit(1)


def register_providers():
    register_provider("atlassian", atlassian.load_provider)
