from collections.abc import Generator
from datetime import (
    datetime,
    timedelta,
)
from typing import Optional

from reconcile.utils.ocm.base import (
    OCMClusterServiceLog,
    OCMClusterServiceLogCreateModel,
)
from reconcile.utils.ocm.search_filters import Filter
from reconcile.utils.ocm_base_client import OCMBaseClient


def get_service_logs(
    ocm_api: OCMBaseClient, filter: Filter
) -> Generator[OCMClusterServiceLog, None, None]:
    """
    Returns a list of service logs matching the given filter.
    """
    for log_dict in ocm_api.get_paginated(
        api_path="/api/service_logs/v1/cluster_logs",
        params={"search": filter.render()},
        max_page_size=100,
    ):
        yield OCMClusterServiceLog(**log_dict)


def create_service_log(
    ocm_api: OCMBaseClient,
    service_log: OCMClusterServiceLogCreateModel,
    dedup_interval: Optional[timedelta] = None,
) -> OCMClusterServiceLog:
    if dedup_interval:
        for previous_log in get_service_logs(
            ocm_api=ocm_api,
            filter=Filter()
            .eq("cluster_uuid", service_log.cluster_uuid)
            .eq("service_name", service_log.service_name)
            .eq("severity", service_log.severity.value)
            .eq("summary", service_log.summary)
            .eq("description", service_log.description)
            .after("created_at", datetime.utcnow() - dedup_interval),
        ):
            return previous_log

    return OCMClusterServiceLog(
        **ocm_api.post(
            api_path="/api/service_logs/v1/cluster_logs",
            data=service_log.dict(by_alias=True),
        )
    )
