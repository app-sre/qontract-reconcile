from datetime import (
    datetime,
    timedelta,
)
from enum import Enum
from typing import (
    Generator,
    Optional,
)

from pydantic import BaseModel

from reconcile.utils.ocm_base_client import OCMBaseClient
from reconcile.utils.ocm.search_filters import Filter


class OCMServiceLogSeverity(Enum):

    Debug = "Debug"
    Info = "Info"
    Warning = "Warning"
    Error = "Error"
    Fatal = "Fatal"


class OCMClusterServiceLog(BaseModel):

    id: str
    href: str
    event_stream_id: str
    username: str

    cluster_id: str
    cluster_uuid: str
    service_name: str
    severity: OCMServiceLogSeverity
    summary: str
    description: str
    timestamp: datetime


def get_service_logs(
    ocm_api: OCMBaseClient, filter: Filter
) -> Generator[OCMClusterServiceLog, None, None]:
    for log_dict in ocm_api.get_paginated(
        api_path="/api/service_logs/v1/cluster_logs",
        params={"search": filter.render()},
        max_page_size=100,
    ):
        yield OCMClusterServiceLog(**log_dict)


def create_service_log(
    ocm_api: OCMBaseClient,
    cluster_uuid: str,
    service_name: str,
    description: str,
    summary: str,
    severity: OCMServiceLogSeverity,
    dedup_interval: Optional[timedelta] = None,
) -> OCMClusterServiceLog:
    if dedup_interval:
        for previous_log in get_service_logs(
            ocm_api=ocm_api,
            filter=Filter()
            .eq("cluster_uuid", cluster_uuid)
            .eq("service_name", service_name)
            .eq("severity", severity.value)
            .eq("summary", summary)
            .eq("description", description)
            .after("created_at", datetime.utcnow() - dedup_interval),
        ):
            return previous_log

    # no similar service log record found... create a new one
    return OCMClusterServiceLog(
        **ocm_api.post(
            api_path="/api/service_logs/v1/cluster_logs",
            data={
                "cluster_uuid": cluster_uuid,
                "service_name": service_name,
                "severity": severity.value,
                "description": description,
                "summary": summary,
            },
        )
    )
