from typing import Callable

import pytest
from httpretty.core import HTTPrettyRequest

from reconcile.test.ocm.fixtures import OcmUrl
from reconcile.test.ocm.test_utils_ocm_get_json import build_paged_ocm_response
from reconcile.utils.ocm_base_client import OCMBaseClient


@pytest.fixture
def ocm_base(access_token_url: str, ocm_url: str) -> OCMBaseClient:
    return OCMBaseClient(
        access_token_client_id="some_client_id",
        access_token_client_secret="some_client_secret",
        access_token_url=access_token_url,
        url=ocm_url,
    )


@pytest.mark.parametrize(
    "nr_of_items, page_size",
    [(10, 3), (10, 2), (1, 10), (10, 10)],
)
def test_get_json_pagination(
    nr_of_items: int,
    page_size: int,
    ocm_api: OCMBaseClient,
    register_ocm_url_responses: Callable[[list[OcmUrl]], int],
    find_all_ocm_http_requests: Callable[[str, str], list[HTTPrettyRequest]],
) -> None:
    register_ocm_url_responses(
        [
            OcmUrl(
                method="GET",
                uri="/api",
                responses=build_paged_ocm_response(
                    nr_of_items=nr_of_items, page_size=page_size
                ),
            )
        ]
    )

    resp = list(ocm_api.get_paginated("/api", max_page_size=page_size))

    assert resp == [{"id": i} for i in range(nr_of_items)]

    ocm_calls = find_all_ocm_http_requests("GET", "/api")
    expected_call_cnt = nr_of_items // page_size

    if nr_of_items % page_size != 0:
        expected_call_cnt += 1

    assert len(ocm_calls) == expected_call_cnt


def test_get_json_pagination_max_pages(
    ocm_api: OCMBaseClient,
    register_ocm_url_responses: Callable[[list[OcmUrl]], int],
    find_all_ocm_http_requests: Callable[[str, str], list[HTTPrettyRequest]],
) -> None:
    nr_of_items = 10
    page_size = 3
    max_pages = 2
    register_ocm_url_responses(
        [
            OcmUrl(
                method="GET",
                uri="/api",
                responses=build_paged_ocm_response(
                    nr_of_items=nr_of_items, page_size=page_size
                ),
            )
        ]
    )
    resp = list(
        ocm_api.get_paginated("/api", max_page_size=page_size, max_pages=max_pages)
    )

    assert resp == [{"id": i} for i in range(nr_of_items // page_size * 2)]

    ocm_calls = find_all_ocm_http_requests("GET", "/api")
    assert len(ocm_calls) == max_pages
