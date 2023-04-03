from collections.abc import Callable
from typing import Any

import pytest
from httpretty.core import HTTPrettyRequest

from reconcile.test.ocm.fixtures import OcmUrl
from reconcile.utils.ocm import OCM


def buid_ocm_item_page(page: int, items: list[Any], total: int) -> dict[str, Any]:
    return {
        "kind": "TestList",
        "page": page,
        "size": len(items),
        "total": total,
        "items": items,
    }


def build_paged_ocm_response(nr_of_items: int, page_size: int) -> list[dict[str, Any]]:
    paged_responses = []
    item_range = range(0, nr_of_items)
    page_nr = 0
    for page_nr, page in enumerate(
        [item_range[i : i + page_size] for i in range(0, nr_of_items, page_size)]
    ):
        items = [{"id": x} for x in page]
        paged_responses.append(buid_ocm_item_page(page_nr + 1, items, nr_of_items))
    paged_responses.append(buid_ocm_item_page(page_nr + 1, [], nr_of_items))
    return paged_responses


@pytest.mark.parametrize(
    "nr_of_items, page_size",
    [(10, 3), (10, 2), (1, 10), (10, 10)],
)
def test_get_json_pagination(
    nr_of_items: int,
    page_size: int,
    ocm: OCM,
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

    resp = ocm._get_json("/api", page_size=page_size)

    assert "kind" in resp
    assert "total" in resp
    assert "items" in resp
    assert len(resp["items"]) == nr_of_items
    assert len(resp["items"]) == resp["total"]

    ocm_calls = find_all_ocm_http_requests("GET", "/api")
    assert len(ocm_calls) == (nr_of_items // page_size) + 1


def test_get_json_empty_list(
    ocm: OCM,
    register_ocm_url_responses: Callable[[list[OcmUrl]], int],
) -> None:
    register_ocm_url_responses(
        [
            OcmUrl(
                method="GET",
                uri="/api",
                responses=build_paged_ocm_response(nr_of_items=0, page_size=10),
            )
        ]
    )

    resp = ocm._get_json("/api", page_size=10)

    assert "kind" in resp
    assert "total" in resp
    assert "items" not in resp


def test_get_json(
    ocm: OCM,
    register_ocm_url_responses: Callable[[list[OcmUrl]], int],
) -> None:
    register_ocm_url_responses(
        [
            OcmUrl(
                method="GET",
                uri="/api",
                responses=[{"kind": "test", "id": 1}],
            )
        ]
    )

    x = ocm._get_json("/api")
    assert x["id"] == 1
