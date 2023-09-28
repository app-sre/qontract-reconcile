from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.typed_queries.dynatrace_log_metrics import (
    get_dynatrace_log_metrics_per_cluster,
)
from reconcile.utils import gql
from reconcile.utils.dynatrace_base_client import init_dynatrace_base_client, DynatraceBaseClient
from reconcile.utils.secret_reader import create_secret_reader

from pydantic import BaseModel, Extra, Field


QONTRACT_INTEGRATION = "dynatrace-log-metrics"


class LogMetric(BaseModel):
    enabled: bool
    key: str
    query: str
    measure: str
    dimensions: list[str]

    class Config:
        extra = Extra.forbid


class LogMetricObject(BaseModel):
    object_id: str = Field(..., alias="objectId")
    value: LogMetric

    class Config:
        extra = Extra.forbid


class LogMetricCollection(BaseModel):
    items: list[LogMetricObject]

    # TODO: handle pagination
    # class Config:
    #     extra = Extra.forbid


def fetch_current_state(client: DynatraceBaseClient) -> None:
    data = client.get("/api/v2/settings/objects?schemaIds=builtin:logmonitoring.schemaless-log-metric")
    metrics_collection = LogMetricCollection(**data)
    print(metrics_collection)

def run(dry_run: bool, thread_pool_size: int) -> None:
    gql_api = gql.get_api()
    vault_settings = get_app_interface_vault_settings()
    secret_reader = create_secret_reader(use_vault=vault_settings.vault)
    clusters = get_dynatrace_log_metrics_per_cluster(gql_api=gql_api)
    for cluster in clusters:
        if not (cluster.dynatrace_environment and cluster.dynatrace_log_metrics):
            continue
        # TODO: this check will be redundant once apiToken is required in schema
        if not cluster.dynatrace_environment.api_token:
            continue
        dt_client = init_dynatrace_base_client(
            url=cluster.dynatrace_environment.environment_url,
            api_token=cluster.dynatrace_environment.api_token,
            secret_reader=secret_reader,
        )
        fetch_current_state(client=dt_client)