import logging

from reconcile.external_resources.manager import (
    ExternalResourcesInventory,
    ExternalResourcesManager,
    setup_factories,
)
from reconcile.external_resources.meta import (
    QONTRACT_INTEGRATION,
    QONTRACT_INTEGRATION_VERSION,
)
from reconcile.external_resources.model import (
    ExternalResourceModule,
    ExternalResourceModuleKey,
    ExternalResourcesSettings,
    ModuleInventory,
)
from reconcile.external_resources.reconciler import K8sExternalResourcesReconciler
from reconcile.external_resources.secrets_sync import (
    build_incluster_secrets_reconciler,
)
from reconcile.external_resources.state import ExternalResourcesStateDynamoDB
from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.typed_queries.external_resources_namespaces import get_namespaces
from reconcile.utils.jobcontroller.controller import (
    build_job_controller,
)
from reconcile.utils.oc import (
    OCCli,
)
from reconcile.utils.openshift_resource import OpenshiftResource, ResourceInventory
from reconcile.utils.secret_reader import create_secret_reader


def fetch_current_state(
    ri: ResourceInventory, oc: OCCli, cluster: str, namespace: str
) -> None:
    for item in oc.get_items("Job", namespace=namespace):
        r = OpenshiftResource(item, QONTRACT_INTEGRATION, QONTRACT_INTEGRATION_VERSION)
        ri.add_current(cluster, namespace, "Job", r.name, r)


def run(
    dry_run: bool,
    cluster: str = "",
    namespace: str = "",
    dry_run_job_suffix: str = "",
) -> None:
    vault_settings = get_app_interface_vault_settings()
    secret_reader = create_secret_reader(use_vault=vault_settings.vault)

    # this will come from app-interface settings
    settings = ExternalResourcesSettings(
        tf_state_bucket="test-external-resources-state",
        tf_state_dynamodb_table="test-external-resources-lock",
        tf_state_region="us-east-1",
        state_dynamodb_table="external-resources-test",
        state_dynamodb_index="index_resources",
    )

    # TODO: Modules need schemas/app-interface objects
    module = ExternalResourceModule(
        provision_provider="aws",
        provider="aws-iam-role",
        module_type="cdktf",
        image="quay.io/app-sre/external-resources-tests",
        default_version="0.0.1",
        reconcile_drift_interval_minutes=24 * 60,
        reconcile_timeout_minutes=30,
    )
    module2 = ExternalResourceModule(
        provision_provider="aws",
        provider="rds",
        module_type="cdktf",
        image="quay.io/app-sre/er-aws-rds",
        default_version="0.0.1",
        reconcile_drift_interval_minutes=-1,  # 24 * 60,
        reconcile_timeout_minutes=60,
    )
    m_key = ExternalResourceModuleKey(provision_provider="aws", provider="aws-iam-role")
    m_key2 = ExternalResourceModuleKey(provision_provider="aws", provider="rds")
    m_inventory = ModuleInventory({m_key: module, m_key2: module2})

    namespaces = [ns for ns in get_namespaces() if ns.external_resources]
    er_inventory = ExternalResourcesInventory(namespaces)

    er_mgr = ExternalResourcesManager(
        settings=settings,
        secret_reader=secret_reader,
        factories=setup_factories(settings, m_inventory, er_inventory, secret_reader),
        er_inventory=er_inventory,
        module_inventory=m_inventory,
        state_manager=ExternalResourcesStateDynamoDB(
            table_name=settings.state_dynamodb_table,
            index_name=settings.state_dynamodb_index,
        ),
        reconciler=K8sExternalResourcesReconciler(
            controller=build_job_controller(
                integration=QONTRACT_INTEGRATION,
                integration_version=QONTRACT_INTEGRATION_VERSION,
                cluster=cluster,
                namespace=namespace,
                secret_reader=secret_reader,
                dry_run=dry_run,
            ),
            dry_run=dry_run,
            dry_run_job_suffix=dry_run_job_suffix,
        ),
        secrets_reconciler=build_incluster_secrets_reconciler(
            cluster, namespace, secret_reader, vault_path="app-sre"
        ),
    )

    if dry_run:
        er_mgr.handle_dry_run_resources()
        if er_mgr.errors:
            logging.error("Validation Errors:")
            for k, e in er_mgr.errors.items():
                logging.error("ExternalResourceKey: %s, Error: %s" % (k, e))
    else:
        er_mgr.handle_resources()
