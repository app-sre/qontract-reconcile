from reconcile.utils.semver_helper import make_semver
from reconcile.typed_queries.saas_files import get_saas_files
from reconcile.utils.secret_reader import create_secret_reader
from reconcile.typed_queries.app_interface_vault_settings import get_app_interface_vault_settings
from reconcile.utils.state import init_state


QONTRACT_INTEGRATION = "saas-pipelines"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)


def run(
    dry_run: bool,
    # TODO: Threadpool not used yet - will be used once we understand scopes in more detail
    thread_pool_size: int,
    defer=None,
) -> None:
    vault_settings = get_app_interface_vault_settings()
    secret_reader = create_secret_reader(use_vault=vault_settings.vault)
    state = init_state(integration=QONTRACT_INTEGRATION, secret_reader=secret_reader)
    saas_files = get_saas_files()
    for saas_file in saas_files:
        for resource_template in saas_file.resource_templates:
            for target in resource_template.targets:
                if not target.promotion:
                    continue
                target.promotion.promotion_data
    print(saas_files)
    print(state)
