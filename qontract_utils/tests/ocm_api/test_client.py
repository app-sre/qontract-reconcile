"""Tests for qontract_utils.ocm_api.client."""

import json
from unittest.mock import MagicMock

import pydantic
import pytest
from pytest_httpserver import HTTPServer
from qontract_utils.hooks import Hooks
from qontract_utils.ocm_api import OcmApi
from qontract_utils.ocm_api.search_filters import Filter
from werkzeug import Request, Response

TOKEN_PATH = "/auth/token"
LABELS_PATH = "/api/accounts_mgmt/v1/labels"
SUBSCRIPTIONS_PATH = "/api/accounts_mgmt/v1/subscriptions"
CLUSTERS_PATH = "/api/clusters_mgmt/v1/clusters"


def _token_response(token: str) -> dict[str, object]:
    return {"access_token": token, "token_type": "bearer", "expires_in": 300}


def _make_ocm_api(
    httpserver: HTTPServer, token: str, hooks: Hooks | None = None
) -> OcmApi:
    httpserver.expect_request(TOKEN_PATH, method="POST").respond_with_json(
        _token_response(token)
    )
    return OcmApi(
        url=httpserver.url_for(""),
        access_token_url=httpserver.url_for(TOKEN_PATH),
        access_token_client_id="client-id",
        access_token_client_secret="client-secret",
        hooks=hooks,
        timeout=5,
    )


def _empty_page() -> dict[str, object]:
    return {"items": [], "page": 1, "size": 0, "total": 0}


#
# token exchange
#


def test_token_fetched_once_at_construction(httpserver: HTTPServer) -> None:
    _make_ocm_api(httpserver, token="test-token")

    token_requests = [req for req, _ in httpserver.log if req.path == TOKEN_PATH]
    assert len(token_requests) == 1
    assert token_requests[0].form.get("grant_type") == "client_credentials"
    assert token_requests[0].form.get("client_id") == "client-id"
    assert token_requests[0].form.get("client_secret") == "client-secret"


def test_bearer_token_sent_on_subsequent_requests(httpserver: HTTPServer) -> None:
    api = _make_ocm_api(httpserver, token="my-secret-token")
    httpserver.expect_request(LABELS_PATH, method="GET").respond_with_json(
        _empty_page()
    )

    api.get_labels(Filter().eq("key", "x"))

    label_requests = [req for req, _ in httpserver.log if req.path == LABELS_PATH]
    assert len(label_requests) == 1
    assert label_requests[0].headers["Authorization"] == "Bearer my-secret-token"


#
# per-instance isolation
#


def test_two_instances_do_not_share_state(
    httpserver: HTTPServer, httpserver_ipv4: HTTPServer
) -> None:
    api1 = _make_ocm_api(httpserver, token="token-1")
    api2 = _make_ocm_api(httpserver_ipv4, token="token-2")
    httpserver.expect_request(LABELS_PATH, method="GET").respond_with_json(
        _empty_page()
    )
    httpserver_ipv4.expect_request(LABELS_PATH, method="GET").respond_with_json(
        _empty_page()
    )

    api1.get_labels(Filter().eq("key", "x"))
    api2.get_labels(Filter().eq("key", "x"))

    req1 = next(req for req, _ in httpserver.log if req.path == LABELS_PATH)
    req2 = next(req for req, _ in httpserver_ipv4.log if req.path == LABELS_PATH)
    assert req1.headers["Authorization"] == "Bearer token-1"
    assert req2.headers["Authorization"] == "Bearer token-2"
    assert api1.url != api2.url


#
# lifecycle
#


def test_context_manager_closes_client(httpserver: HTTPServer) -> None:
    with _make_ocm_api(httpserver, token="test-token") as api:
        assert not api._client.is_closed
    assert api._client.is_closed


#
# pagination
#


def _label_json(key: str, label_type: str, ref_id: str) -> dict[str, object]:
    label: dict[str, object] = {
        "id": f"label-{key}",
        "key": key,
        "value": "v",
        "type": label_type,
    }
    if label_type == "Subscription":
        label["subscription_id"] = ref_id
    else:
        label["organization_id"] = ref_id
    return label


def test_get_labels_paginates_across_pages(httpserver: HTTPServer) -> None:
    api = _make_ocm_api(httpserver, token="test-token")

    def handler(request: Request) -> Response:
        page = int(request.args.get("page", "1"))
        if page == 1:
            items = [_label_json(f"k{i}", "Subscription", "sub-1") for i in range(100)]
            body = {"items": items, "page": 1, "size": 100, "total": 101}
        else:
            items = [_label_json("k100", "Organization", "org-1")]
            body = {"items": items, "page": 2, "size": 1, "total": 101}
        return Response(json.dumps(body), content_type="application/json")

    httpserver.expect_request(LABELS_PATH, method="GET").respond_with_handler(handler)

    labels = api.get_labels(Filter().like("key", "k%"))

    assert len(labels) == 101
    label_requests = [req for req, _ in httpserver.log if req.path == LABELS_PATH]
    assert len(label_requests) == 2
    assert label_requests[0].args["orderBy"] == "created_at"
    assert label_requests[0].args["search"] == "key like 'k%'"
    assert label_requests[0].args["page"] == "1"
    assert label_requests[1].args["page"] == "2"


def test_get_subscriptions_chunks_by_id(httpserver: HTTPServer) -> None:
    api = _make_ocm_api(httpserver, token="test-token")
    ids = [f"sub-{i}" for i in range(150)]
    call_count = {"n": 0}

    def handler(request: Request) -> Response:
        _ = request
        call_count["n"] += 1
        body = {
            "items": [
                {
                    "id": f"result-sub-{call_count['n']}",
                    "organization_id": "org-1",
                    "status": "Active",
                    "managed": True,
                }
            ],
            "page": 1,
            "size": 1,
            "total": 1,
        }
        return Response(json.dumps(body), content_type="application/json")

    httpserver.expect_request(SUBSCRIPTIONS_PATH, method="GET").respond_with_handler(
        handler
    )

    result = api.get_subscriptions(Filter().is_in("id", ids))

    assert call_count["n"] == 2  # 150 ids chunked into groups of 100 -> 2 requests
    assert set(result.keys()) == {"result-sub-1", "result-sub-2"}
    subscription_requests = [
        req for req, _ in httpserver.log if req.path == SUBSCRIPTIONS_PATH
    ]
    assert all(req.args.get("fetchLabels") == "true" for req in subscription_requests)
    assert all(
        req.args.get("fetchCapabilities") == "true" for req in subscription_requests
    )
    assert all(req.args.get("orderBy") == "id" for req in subscription_requests)


def test_get_clusters_maps_fields(httpserver: HTTPServer) -> None:
    api = _make_ocm_api(httpserver, token="test-token")
    body = {
        "items": [
            {
                "id": "cluster-1",
                "name": "my-cluster",
                "subscription": {"id": "sub-1"},
                "console": {"url": "https://console.example.com"},
                "external_auth_config": {"enabled": True},
            },
            {
                "id": "cluster-2",
                "name": "no-console-cluster",
                "subscription": {"id": "sub-2"},
            },
        ],
        "page": 1,
        "size": 2,
        "total": 2,
    }
    httpserver.expect_request(CLUSTERS_PATH, method="GET").respond_with_json(body)

    clusters = api.get_clusters(Filter().eq("managed", "true"))

    assert len(clusters) == 2
    cluster_1 = next(c for c in clusters if c.id == "cluster-1")
    assert cluster_1.console_url == "https://console.example.com"
    assert cluster_1.external_auth_enabled is True
    assert cluster_1.subscription_id == "sub-1"
    cluster_2 = next(c for c in clusters if c.id == "cluster-2")
    assert cluster_2.console_url is None
    assert cluster_2.external_auth_enabled is False

    cluster_requests = [req for req, _ in httpserver.log if req.path == CLUSTERS_PATH]
    assert cluster_requests[0].args["order"] == "creation_timestamp"


#
# hooks
#


def test_pre_hooks_includes_metrics(httpserver: HTTPServer) -> None:
    api = _make_ocm_api(httpserver, token="test-token")

    assert len(api._hooks.pre_hooks) >= 1


def test_custom_hooks_appended_after_builtin(httpserver: HTTPServer) -> None:
    custom_hook = MagicMock()

    api = _make_ocm_api(
        httpserver, token="test-token", hooks=Hooks(pre_hooks=[custom_hook])
    )

    assert custom_hook in api._hooks.pre_hooks
    # built-in: metrics, request_log, latency_start = 3, + 1 custom = 4
    assert len(api._hooks.pre_hooks) == 4


#
# label parsing validation (RawLabel is a pydantic discriminated union on "type")
#


def _label_page(raw_label: dict[str, object]) -> dict[str, object]:
    return {"items": [raw_label], "page": 1, "size": 1, "total": 1}


def test_get_labels_subscription_missing_id_raises(httpserver: HTTPServer) -> None:
    api = _make_ocm_api(httpserver, token="test-token")
    httpserver.expect_request(LABELS_PATH, method="GET").respond_with_json(
        _label_page({"id": "l1", "key": "k", "value": "v", "type": "Subscription"})
    )

    with pytest.raises(pydantic.ValidationError, match="subscription_id"):
        api.get_labels(Filter().eq("key", "k"))


def test_get_labels_organization_missing_id_raises(httpserver: HTTPServer) -> None:
    api = _make_ocm_api(httpserver, token="test-token")
    httpserver.expect_request(LABELS_PATH, method="GET").respond_with_json(
        _label_page({"id": "l1", "key": "k", "value": "v", "type": "Organization"})
    )

    with pytest.raises(pydantic.ValidationError, match="organization_id"):
        api.get_labels(Filter().eq("key", "k"))


def test_get_labels_unsupported_type_raises(httpserver: HTTPServer) -> None:
    api = _make_ocm_api(httpserver, token="test-token")
    httpserver.expect_request(LABELS_PATH, method="GET").respond_with_json(
        _label_page({"id": "l1", "key": "k", "value": "v", "type": "Account"})
    )

    with pytest.raises(pydantic.ValidationError, match="union_tag_invalid"):
        api.get_labels(Filter().eq("key", "k"))
