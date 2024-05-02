import logging
from typing import Callable

from reconcile.external_resources.manager import (
    ExternalResourcesInventory,
    ExternalResourcesManager,
    setup_factories,
)
from reconcile.external_resources.meta import (
    QONTRACT_INTEGRATION,
    QONTRACT_INTEGRATION_VERSION,
)
from reconcile.external_resources.model import load_module_inventory
from reconcile.external_resources.reconciler import K8sExternalResourcesReconciler
from reconcile.external_resources.secrets_sync import (
    build_incluster_secrets_reconciler,
)
from reconcile.external_resources.state import ExternalResourcesStateDynamoDB
from reconcile.gql_definitions.external_resources.aws_accounts import (
    query as aws_accounts_query,
)
from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.typed_queries.external_resources import (
    get_modules,
    get_namespaces,
    get_settings,
)
from reconcile.utils import gql
from reconcile.utils.aws_api_typed.api import AWSApi, AWSStaticCredentials
from reconcile.utils.jobcontroller.controller import (
    build_job_controller,
)
from reconcile.utils.oc import (
    OCCli,
)
from reconcile.utils.openshift_resource import OpenshiftResource, ResourceInventory
from reconcile.utils.secret_reader import SecretReaderBase, create_secret_reader


def fetch_current_state(
    ri: ResourceInventory, oc: OCCli, cluster: str, namespace: str
) -> None:
    for item in oc.get_items("Job", namespace=namespace):
        r = OpenshiftResource(item, QONTRACT_INTEGRATION, QONTRACT_INTEGRATION_VERSION)
        ri.add_current(cluster, namespace, "Job", r.name, r)


def get_aws_api(
    query_func: Callable,
    account_name: str,
    region: str,
    secret_reader: SecretReaderBase,
) -> AWSApi:
    accounts = (
        aws_accounts_query(
            query_func, variables={"filter": {"name": account_name}}
        ).accounts
        or []
    )
    if not accounts:
        raise Exception(
            "External Resources configured AWS account does not exist or can not be found"
        )
    account = accounts[0]
    automation_token = secret_reader.read_all_secret(account.automation_token)
    aws_credentials = AWSStaticCredentials(
        access_key_id=automation_token["aws_access_key_id"],
        secret_access_key=automation_token["aws_secret_access_key"],
        region=region,
    )
    return AWSApi(aws_credentials)


def run(
    dry_run: bool,
    dry_run_job_suffix: str,
    thread_pool_size: int,
    workers_cluster: str | None = None,
    workers_namespace: str | None = None,
) -> None:
    vault_settings = get_app_interface_vault_settings()
    secret_reader = create_secret_reader(use_vault=vault_settings.vault)
    er_settings = get_settings()[0]
    m_inventory = load_module_inventory(get_modules())
    namespaces = [ns for ns in get_namespaces() if ns.external_resources]
    er_inventory = ExternalResourcesInventory(namespaces)

    if not workers_cluster:
        workers_cluster = er_settings.workers_cluster.name
    if not workers_namespace:
        workers_namespace = er_settings.workers_namespace.name

    with get_aws_api(
        query_func=gql.get_api().query,
        account_name=er_settings.state_dynamodb_account.name,
        region=er_settings.state_dynamodb_region,
        secret_reader=secret_reader,
    ) as aws_api:
        er_mgr = ExternalResourcesManager(
            thread_pool_size=thread_pool_size,
            settings=er_settings,
            secret_reader=secret_reader,
            factories=setup_factories(
                er_settings, m_inventory, er_inventory, secret_reader
            ),
            er_inventory=er_inventory,
            module_inventory=m_inventory,
            state_manager=ExternalResourcesStateDynamoDB(
                aws_api=aws_api,
                table_name=er_settings.state_dynamodb_table,
            ),
            reconciler=K8sExternalResourcesReconciler(
                controller=build_job_controller(
                    integration=QONTRACT_INTEGRATION,
                    integration_version=QONTRACT_INTEGRATION_VERSION,
                    cluster=workers_cluster,
                    namespace=workers_namespace,
                    secret_reader=secret_reader,
                    dry_run=dry_run,
                ),
                dry_run=dry_run,
                dry_run_job_suffix=dry_run_job_suffix,
            ),
            secrets_reconciler=build_incluster_secrets_reconciler(
                workers_cluster, workers_namespace, secret_reader, vault_path="app-sre"
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
