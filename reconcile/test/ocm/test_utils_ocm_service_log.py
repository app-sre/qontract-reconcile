from collections.abc import Callable
from datetime import (
    datetime,
    timedelta,
    timezone,
)
from typing import Optional

import pytest
from httpretty.core import HTTPrettyRequest
from pytest_mock import MockerFixture

from reconcile.test.ocm.fixtures import OcmUrl
from reconcile.utils.ocm import service_log
from reconcile.utils.ocm.base import (
    OCMClusterServiceLog,
    OCMClusterServiceLogCreateModel,
    OCMServiceLogSeverity,
)
from reconcile.utils.ocm.search_filters import (
    DateRangeCondition,
    Filter,
)
from reconcile.utils.ocm.service_log import (
    CLUSTER_SERVICE_LOGS_CREATE_ENDPOINT,
    CLUSTER_SERVICE_LOGS_LIST_ENDPOINT,
    create_service_log,
    get_service_logs_for_cluster_uuid,
)
from reconcile.utils.ocm_base_client import OCMBaseClient


def build_service_log(
    summary: str = "",
    description: str = "",
    cluster_uuid: str = "",
    service_name: str = "some-service",
    severity: OCMServiceLogSeverity = OCMServiceLogSeverity.Info,
    timestamp: datetime = datetime(2020, 1, 2, 0, 0, 0, 0, tzinfo=timezone.utc),
) -> OCMClusterServiceLog:
    return OCMClusterServiceLog(
        id="",
        href="",
        event_stream_id="",
        username="",
        cluster_uuid=cluster_uuid,
        cluster_id="",
        service_name=service_name,
        severity=severity,
        description=description,
        summary=summary,
        timestamp=timestamp,
    )


@pytest.fixture
def example_service_log(
    register_ocm_url_responses: Callable[[list[OcmUrl]], int],
) -> OCMClusterServiceLog:
    expected_service_log = build_service_log(
        "some error",
        "description",
        "cluster_uuid",
        severity=OCMServiceLogSeverity.Error,
    )
    register_ocm_url_responses(
        [
            OcmUrl(
                method="GET", uri=CLUSTER_SERVICE_LOGS_LIST_ENDPOINT
            ).add_list_response([expected_service_log])
        ]
    )

    return expected_service_log


def test_get_service_logs_for_cluster_uuid(
    ocm_api: OCMBaseClient,
    example_service_log: OCMClusterServiceLog,
    find_ocm_http_request: Callable[[str, str], Optional[HTTPrettyRequest]],
) -> None:
    cluster_uuid = "cluster_uuid"
    fetched_logs = list(
        get_service_logs_for_cluster_uuid(
            ocm_api=ocm_api,
            cluster_uuid=cluster_uuid,
        )
    )
    assert [example_service_log] == fetched_logs
    get_request = find_ocm_http_request("GET", CLUSTER_SERVICE_LOGS_LIST_ENDPOINT)
    assert get_request
    assert get_request.querystring["cluster_uuid"] == [cluster_uuid]


def test_get_service_logs_for_cluster_uuid_with_filter(
    ocm_api: OCMBaseClient,
    example_service_log: OCMClusterServiceLog,
    find_ocm_http_request: Callable[[str, str], Optional[HTTPrettyRequest]],
) -> None:
    cluster_uuid = "cluster_uuid"
    service_filter = Filter().eq("service_name", "some-service")
    fetched_logs = list(
        get_service_logs_for_cluster_uuid(
            ocm_api=ocm_api,
            cluster_uuid=cluster_uuid,
            filter=service_filter,
        )
    )
    assert [example_service_log] == fetched_logs
    get_request = find_ocm_http_request("GET", CLUSTER_SERVICE_LOGS_LIST_ENDPOINT)
    assert get_request
    assert get_request.querystring["cluster_uuid"] == [cluster_uuid]
    assert get_request.querystring["search"] == [service_filter.render()]


def test_create_service_log(
    ocm_api: OCMBaseClient,
    register_ocm_url_responses: Callable[[list[OcmUrl]], int],
    find_ocm_http_request: Callable[[str, str], Optional[HTTPrettyRequest]],
) -> None:
    timestamp = datetime(2020, 1, 2, 0, 0, 0, 0, tzinfo=timezone.utc)
    register_ocm_url_responses(
        [
            OcmUrl(
                method="POST",
                uri=CLUSTER_SERVICE_LOGS_CREATE_ENDPOINT,
                responses=[
                    build_service_log(
                        cluster_uuid="cluster_uuid",
                        summary="something happened",
                        description="something happenes",
                        service_name="some-service",
                        severity=OCMServiceLogSeverity.Info,
                        timestamp=timestamp,
                    ),
                ],
            )
        ]
    )
    result = create_service_log(
        ocm_api=ocm_api,
        service_log=OCMClusterServiceLogCreateModel(
            cluster_uuid="cluster_uuid",
            summary="something happened",
            description="something happenes",
            service_name="some-service",
            severity=OCMServiceLogSeverity.Info,
        ),
    )
    assert result is not None

    assert find_ocm_http_request("POST", CLUSTER_SERVICE_LOGS_CREATE_ENDPOINT)


def test_create_service_log_dedup_timedelta_filter(
    ocm_api: OCMBaseClient, mocker: MockerFixture
) -> None:
    get_service_logs_mock = mocker.patch.object(
        service_log, "get_service_logs_for_cluster_uuid"
    )
    get_service_logs_mock.return_value = iter(
        [
            build_service_log(
                "some error",
                "description",
                "cluster_uuid",
                severity=OCMServiceLogSeverity.Error,
            )
        ]
    )

    dedup_interval = timedelta(days=1)
    create_service_log(
        ocm_api=ocm_api,
        service_log=OCMClusterServiceLogCreateModel(
            cluster_uuid="cluster_uuid",
            summary="something happened",
            description="something happenes",
            service_name="some-service",
            severity=OCMServiceLogSeverity.Info,
        ),
        dedup_interval=dedup_interval,
    )
    get_service_logs_filter = get_service_logs_mock.call_args.kwargs["filter"]
    assert isinstance(get_service_logs_filter, Filter)
    daterange_condition = get_service_logs_filter.condition_by_key("created_at")
    assert isinstance(daterange_condition, DateRangeCondition)
    assert daterange_condition.start is not None
    assert daterange_condition.end is None
    resolved_start = daterange_condition.resolve_start()
    assert resolved_start
    assert datetime.timestamp(datetime.utcnow() - dedup_interval) == pytest.approx(
        datetime.timestamp(resolved_start),
        abs=5,  # allow 5 seconds of difference when comparing
    )


def test_create_service_log_dedup(
    ocm_api: OCMBaseClient,
    example_service_log: OCMClusterServiceLog,
    find_ocm_http_request: Callable[[str, str], Optional[HTTPrettyRequest]],
) -> None:
    create_service_log(
        ocm_api=ocm_api,
        service_log=OCMClusterServiceLogCreateModel(
            cluster_uuid="cluster_uuid",
            summary="something happened",
            description="something happenes",
            service_name="some-service",
            severity=OCMServiceLogSeverity.Info,
        ),
        dedup_interval=timedelta(days=1),
    )
    # expect no post call to the service log api
    assert find_ocm_http_request("POST", CLUSTER_SERVICE_LOGS_CREATE_ENDPOINT) is None


def test_create_service_log_dedup_no_dup(
    ocm_api: OCMBaseClient,
    register_ocm_url_responses: Callable[[list[OcmUrl]], int],
    find_ocm_http_request: Callable[[str, str], Optional[HTTPrettyRequest]],
) -> None:
    register_ocm_url_responses(
        [
            OcmUrl(
                method="GET", uri=CLUSTER_SERVICE_LOGS_LIST_ENDPOINT
            ).add_list_response([]),
            OcmUrl(
                method="POST",
                uri=CLUSTER_SERVICE_LOGS_CREATE_ENDPOINT,
                responses=[build_service_log()],
            ),
        ]
    )

    create_service_log(
        ocm_api=ocm_api,
        service_log=OCMClusterServiceLogCreateModel(
            cluster_uuid="cluster_uuid",
            summary="SOMETHING ELSE HAPPENED",
            description="something happenes",
            service_name="some-service",
            severity=OCMServiceLogSeverity.Info,
        ),
        dedup_interval=timedelta(days=1),
    )
    # expect a post call to the service log api
    assert find_ocm_http_request("POST", CLUSTER_SERVICE_LOGS_CREATE_ENDPOINT)
