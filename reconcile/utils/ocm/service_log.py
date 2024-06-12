from collections.abc import Generator
from datetime import (
    datetime,
    timedelta,
)

from reconcile.utils.ocm.base import (
    OCMClusterServiceLog,
    OCMClusterServiceLogCreateModel,
)
from reconcile.utils.ocm.search_filters import Filter
from reconcile.utils.ocm_base_client import OCMBaseClient

CLUSTER_SERVICE_LOGS_LIST_ENDPOINT = "/api/service_logs/v1/clusters/cluster_logs"
CLUSTER_SERVICE_LOGS_CREATE_ENDPOINT = "/api/service_logs/v1/cluster_logs"


def get_service_logs_for_cluster_uuid(
    ocm_api: OCMBaseClient, cluster_uuid: str, filter: Filter | None = None
) -> Generator[OCMClusterServiceLog, None, None]:
    """
    Returns a list of service logs for a cluster, matching the optional filter.
    """
    params = {"cluster_uuid": cluster_uuid}
    if filter:
        params["search"] = filter.render()
    for log_dict in ocm_api.get_paginated(
        api_path=CLUSTER_SERVICE_LOGS_LIST_ENDPOINT,
        params=params,
        max_page_size=100,
    ):
        yield OCMClusterServiceLog(**log_dict)


def create_service_log(
    ocm_api: OCMBaseClient,
    service_log: OCMClusterServiceLogCreateModel,
    dedup_interval: timedelta | None = None,
) -> OCMClusterServiceLog:
    if dedup_interval:
        previous_log = next(
            get_service_logs_for_cluster_uuid(
                ocm_api=ocm_api,
                cluster_uuid=service_log.cluster_uuid,
                filter=Filter()
                .eq("service_name", service_log.service_name)
                .eq("severity", service_log.severity.value)
                .eq("summary", service_log.summary)
                .eq("description", service_log.description)
                .after("created_at", datetime.utcnow() - dedup_interval),
            ),
            None,
        )
        if previous_log:
            return previous_log

    return OCMClusterServiceLog(
        **ocm_api.post(
            api_path=CLUSTER_SERVICE_LOGS_CREATE_ENDPOINT,
            data=service_log.dict(by_alias=True),
        )
    )
