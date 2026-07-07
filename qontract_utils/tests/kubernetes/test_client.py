"""Tests for qontract_utils.kubernetes.client module."""

import json
from unittest.mock import MagicMock

import pytest
from prometheus_client import REGISTRY
from pytest_httpserver import HTTPServer
from qontract_utils.hooks import Hooks
from qontract_utils.kubernetes.client import KubernetesApi, KubernetesApiCallContext
from qontract_utils.kubernetes.exceptions import (
    ForbiddenError,
    KubernetesApiError,
    NotFoundError,
)
from werkzeug import Request, Response

from .conftest import (
    k8s_namespace_json,
    k8s_namespace_list_json,
    k8s_project_json,
    k8s_project_list_json,
    k8s_status_json,
    mock_project_discovery,
)

# --- Connection ---


def test_connection_sends_auth_header(httpserver: HTTPServer) -> None:
    """Test that the client sends the bearer token in Authorization header."""
    received_headers: dict[str, str] = {}

    def capture_headers(request: Request) -> Response:
        received_headers.update(dict(request.headers))
        return Response(
            json.dumps(k8s_namespace_json("test-ns")),
            status=200,
            content_type="application/json",
        )

    httpserver.expect_request(
        "/api/v1/namespaces/test-ns",
    ).respond_with_handler(capture_headers)

    api = KubernetesApi(
        server=httpserver.url_for(""),
        token="my-secret-token",
    )
    api.get_namespace("test-ns")

    assert "Bearer my-secret-token" in received_headers.get("Authorization", "")


# --- get_namespace ---


def test_get_namespace_success(httpserver: HTTPServer, k8s_api: KubernetesApi) -> None:
    """Test getting a namespace by name."""
    httpserver.expect_request(
        "/api/v1/namespaces/my-ns",
    ).respond_with_json(k8s_namespace_json("my-ns"))

    ns = k8s_api.get_namespace("my-ns")
    assert ns.metadata is not None
    assert ns.metadata.name == "my-ns"


def test_get_namespace_not_found(
    httpserver: HTTPServer, k8s_api: KubernetesApi
) -> None:
    """Test that getting a non-existent namespace raises NotFoundError."""
    httpserver.expect_request(
        "/api/v1/namespaces/nope",
    ).respond_with_json(
        k8s_status_json(404, "NotFound", 'namespaces "nope" not found'),
        status=404,
    )

    with pytest.raises(NotFoundError, match="nope"):
        k8s_api.get_namespace("nope")


def test_get_namespace_forbidden(
    httpserver: HTTPServer, k8s_api: KubernetesApi
) -> None:
    """Test that a 403 raises ForbiddenError."""
    httpserver.expect_request(
        "/api/v1/namespaces/secret",
    ).respond_with_json(
        k8s_status_json(403, "Forbidden", "forbidden"),
        status=403,
    )

    with pytest.raises(ForbiddenError):
        k8s_api.get_namespace("secret")


# --- list_namespaces ---


def test_list_namespaces_success(
    httpserver: HTTPServer, k8s_api: KubernetesApi
) -> None:
    """Test listing namespaces returns all namespaces."""
    httpserver.expect_request(
        "/api/v1/namespaces",
    ).respond_with_json(k8s_namespace_list_json(["ns-a", "ns-b", "ns-c"]))

    namespaces = k8s_api.list_namespaces()
    assert len(namespaces) == 3
    names = [ns.metadata.name for ns in namespaces if ns.metadata]
    assert names == ["ns-a", "ns-b", "ns-c"]


def test_list_namespaces_empty(httpserver: HTTPServer, k8s_api: KubernetesApi) -> None:
    """Test listing namespaces when none exist."""
    httpserver.expect_request(
        "/api/v1/namespaces",
    ).respond_with_json(k8s_namespace_list_json([]))

    namespaces = k8s_api.list_namespaces()
    assert namespaces == []


# --- namespace_exists ---


def test_namespace_exists_true(httpserver: HTTPServer, k8s_api: KubernetesApi) -> None:
    """Test namespace_exists returns True when namespace exists."""
    httpserver.expect_request(
        "/api/v1/namespaces/existing",
    ).respond_with_json(k8s_namespace_json("existing"))

    assert k8s_api.namespace_exists("existing") is True


def test_namespace_exists_false(httpserver: HTTPServer, k8s_api: KubernetesApi) -> None:
    """Test namespace_exists returns False when namespace doesn't exist."""
    httpserver.expect_request(
        "/api/v1/namespaces/missing",
    ).respond_with_json(
        k8s_status_json(404, "NotFound", 'namespaces "missing" not found'),
        status=404,
    )

    assert k8s_api.namespace_exists("missing") is False


# --- create_namespace ---


def test_create_namespace_success(
    httpserver: HTTPServer, k8s_api: KubernetesApi
) -> None:
    """Test creating a new namespace."""
    httpserver.expect_request(
        "/api/v1/namespaces",
        method="POST",
    ).respond_with_json(k8s_namespace_json("new-ns"), status=201)

    ns = k8s_api.create_namespace("new-ns")
    assert ns.metadata is not None
    assert ns.metadata.name == "new-ns"


def test_create_namespace_idempotent_409(
    httpserver: HTTPServer, k8s_api: KubernetesApi
) -> None:
    """Test that creating an already-existing namespace returns it (409 handled)."""
    httpserver.expect_ordered_request(
        "/api/v1/namespaces",
        method="POST",
    ).respond_with_json(
        k8s_status_json(409, "AlreadyExists", 'namespaces "exists" already exists'),
        status=409,
    )
    httpserver.expect_ordered_request(
        "/api/v1/namespaces/exists",
        method="GET",
    ).respond_with_json(k8s_namespace_json("exists"))

    ns = k8s_api.create_namespace("exists")
    assert ns.metadata is not None
    assert ns.metadata.name == "exists"


# --- delete_namespace ---


def test_delete_namespace_success(
    httpserver: HTTPServer, k8s_api: KubernetesApi
) -> None:
    """Test deleting a namespace."""
    httpserver.expect_request(
        "/api/v1/namespaces/old-ns",
        method="DELETE",
    ).respond_with_json(k8s_namespace_json("old-ns"))

    k8s_api.delete_namespace("old-ns")


def test_delete_namespace_idempotent_404(
    httpserver: HTTPServer, k8s_api: KubernetesApi
) -> None:
    """Test that deleting a non-existent namespace is silently ignored."""
    httpserver.expect_request(
        "/api/v1/namespaces/gone",
        method="DELETE",
    ).respond_with_json(
        k8s_status_json(404, "NotFound", 'namespaces "gone" not found'),
        status=404,
    )

    k8s_api.delete_namespace("gone")


def test_delete_namespace_forbidden(
    httpserver: HTTPServer, k8s_api: KubernetesApi
) -> None:
    """Test that delete with 403 raises ForbiddenError."""
    httpserver.expect_request(
        "/api/v1/namespaces/protected",
        method="DELETE",
    ).respond_with_json(
        k8s_status_json(403, "Forbidden", "forbidden"),
        status=403,
    )

    with pytest.raises(ForbiddenError):
        k8s_api.delete_namespace("protected")


# --- OpenShift Project detection ---


def test_supports_projects_true_on_openshift(httpserver: HTTPServer) -> None:
    """Test that _supports_projects() returns True when Project API exists."""
    mock_project_discovery(httpserver)
    api = KubernetesApi(
        server=httpserver.url_for(""),
        token="test-token",
    )
    assert api._supports_projects() is True


def test_supports_projects_false_on_vanilla_k8s(httpserver: HTTPServer) -> None:
    """Test that _supports_projects() returns False when Project API is missing."""
    httpserver.expect_request(
        "/apis/project.openshift.io/v1/projects",
        method="GET",
    ).respond_with_json(
        k8s_status_json(
            404, "NotFound", "the server could not find the requested resource"
        ),
        status=404,
    )
    api = KubernetesApi(
        server=httpserver.url_for(""),
        token="test-token",
    )
    assert api._supports_projects() is False


def test_supports_projects_true_on_403(httpserver: HTTPServer) -> None:
    """Test that 403 (no list permission) still detects Projects as supported."""
    httpserver.expect_request(
        "/apis/project.openshift.io/v1/projects",
        method="GET",
    ).respond_with_json(
        k8s_status_json(403, "Forbidden", "forbidden"),
        status=403,
    )
    api = KubernetesApi(
        server=httpserver.url_for(""),
        token="test-token",
    )
    assert api._supports_projects() is True


def test_supports_projects_cached(httpserver: HTTPServer) -> None:
    """Test that discovery result is cached (only one API call)."""
    httpserver.expect_request(
        "/apis/project.openshift.io/v1/projects",
        method="GET",
    ).respond_with_json(k8s_project_list_json([]))

    api = KubernetesApi(
        server=httpserver.url_for(""),
        token="test-token",
    )
    assert api._supports_projects() is True
    assert api._supports_projects() is True
    assert len(httpserver.log) == 1


def test_supports_projects_raises_on_unexpected_error(httpserver: HTTPServer) -> None:
    """Test that unexpected errors (500, 401) are raised, not cached as False."""
    httpserver.expect_request(
        "/apis/project.openshift.io/v1/projects",
        method="GET",
    ).respond_with_json(
        k8s_status_json(500, "InternalError", "internal server error"),
        status=500,
    )
    api = KubernetesApi(
        server=httpserver.url_for(""),
        token="test-token",
    )
    with pytest.raises(KubernetesApiError, match="internal server error"):
        api._supports_projects()
    assert api._has_projects is None


# --- namespace_exists with Projects ---


def test_namespace_exists_uses_project_on_openshift(
    httpserver: HTTPServer, k8s_api_openshift: KubernetesApi
) -> None:
    """On OpenShift, namespace_exists checks the Project API."""
    httpserver.expect_request(
        "/apis/project.openshift.io/v1/projects/my-ns",
    ).respond_with_json(k8s_project_json("my-ns"))

    assert k8s_api_openshift.namespace_exists("my-ns") is True


def test_namespace_exists_false_via_project(
    httpserver: HTTPServer, k8s_api_openshift: KubernetesApi
) -> None:
    """On OpenShift, namespace_exists returns False via Project 404."""
    httpserver.expect_request(
        "/apis/project.openshift.io/v1/projects/missing",
    ).respond_with_json(
        k8s_status_json(404, "NotFound", 'projects "missing" not found'),
        status=404,
    )

    assert k8s_api_openshift.namespace_exists("missing") is False


def test_namespace_exists_uses_namespace_for_openshift_prefix(
    httpserver: HTTPServer, k8s_api_openshift: KubernetesApi
) -> None:
    """openshift-* namespaces use Namespace API even on OpenShift."""
    httpserver.expect_request(
        "/api/v1/namespaces/openshift-monitoring",
    ).respond_with_json(k8s_namespace_json("openshift-monitoring"))

    assert k8s_api_openshift.namespace_exists("openshift-monitoring") is True


# --- create_namespace with Projects ---


def test_create_namespace_uses_project_on_openshift(
    httpserver: HTTPServer, k8s_api_openshift: KubernetesApi
) -> None:
    """On OpenShift, create_namespace creates a Project then returns Namespace."""
    httpserver.expect_ordered_request(
        "/apis/project.openshift.io/v1/projects",
        method="POST",
    ).respond_with_json(k8s_project_json("new-ns"), status=201)
    httpserver.expect_ordered_request(
        "/api/v1/namespaces/new-ns",
        method="GET",
    ).respond_with_json(k8s_namespace_json("new-ns"))

    ns = k8s_api_openshift.create_namespace("new-ns")
    assert ns.metadata is not None
    assert ns.metadata.name == "new-ns"


def test_create_namespace_project_idempotent_409(
    httpserver: HTTPServer, k8s_api_openshift: KubernetesApi
) -> None:
    """On OpenShift, 409 on Project create is handled (idempotent)."""
    httpserver.expect_ordered_request(
        "/apis/project.openshift.io/v1/projects",
        method="POST",
    ).respond_with_json(
        k8s_status_json(409, "AlreadyExists", 'projects "exists" already exists'),
        status=409,
    )
    httpserver.expect_ordered_request(
        "/api/v1/namespaces/exists",
        method="GET",
    ).respond_with_json(k8s_namespace_json("exists"))

    ns = k8s_api_openshift.create_namespace("exists")
    assert ns.metadata is not None
    assert ns.metadata.name == "exists"


def test_create_namespace_uses_namespace_for_openshift_prefix(
    httpserver: HTTPServer, k8s_api_openshift: KubernetesApi
) -> None:
    """openshift-* namespaces use Namespace API even on OpenShift."""
    httpserver.expect_request(
        "/api/v1/namespaces",
        method="POST",
    ).respond_with_json(k8s_namespace_json("openshift-monitoring"), status=201)

    ns = k8s_api_openshift.create_namespace("openshift-monitoring")
    assert ns.metadata is not None
    assert ns.metadata.name == "openshift-monitoring"


# --- delete_namespace with Projects ---


def test_delete_namespace_uses_project_on_openshift(
    httpserver: HTTPServer, k8s_api_openshift: KubernetesApi
) -> None:
    """On OpenShift, delete_namespace deletes the Project."""
    httpserver.expect_request(
        "/apis/project.openshift.io/v1/projects/old-ns",
        method="DELETE",
    ).respond_with_json(k8s_project_json("old-ns"))

    k8s_api_openshift.delete_namespace("old-ns")


def test_delete_namespace_project_idempotent_404(
    httpserver: HTTPServer, k8s_api_openshift: KubernetesApi
) -> None:
    """On OpenShift, deleting non-existent Project is silently ignored."""
    httpserver.expect_request(
        "/apis/project.openshift.io/v1/projects/gone",
        method="DELETE",
    ).respond_with_json(
        k8s_status_json(404, "NotFound", 'projects "gone" not found'),
        status=404,
    )

    k8s_api_openshift.delete_namespace("gone")


def test_delete_namespace_uses_namespace_for_openshift_prefix(
    httpserver: HTTPServer, k8s_api_openshift: KubernetesApi
) -> None:
    """openshift-* namespaces use Namespace API even on OpenShift."""
    httpserver.expect_request(
        "/api/v1/namespaces/openshift-config",
        method="DELETE",
    ).respond_with_json(k8s_namespace_json("openshift-config"))

    k8s_api_openshift.delete_namespace("openshift-config")


# --- Hooks ---


def test_hooks_called_with_correct_context(
    httpserver: HTTPServer,
) -> None:
    """Test that hooks receive correct KubernetesApiCallContext."""
    hook = MagicMock()

    httpserver.expect_request(
        "/api/v1/namespaces/test-ns",
    ).respond_with_json(k8s_namespace_json("test-ns"))

    api = KubernetesApi(
        server=httpserver.url_for(""),
        token="test-token",
        hooks=Hooks(pre_hooks=[hook]),
    )
    api.get_namespace("test-ns")

    hook.assert_called_once()
    context = hook.call_args[0][0]
    assert isinstance(context, KubernetesApiCallContext)
    assert context.method == "namespaces.get"
    assert context.verb == "GET"


def test_custom_hooks_merge_with_builtin(
    httpserver: HTTPServer,
) -> None:
    """Test that user hooks merge with built-in hooks."""
    user_hook = MagicMock()

    httpserver.expect_request(
        "/api/v1/namespaces/test-ns",
    ).respond_with_json(k8s_namespace_json("test-ns"))

    api = KubernetesApi(
        server=httpserver.url_for(""),
        token="test-token",
        hooks=Hooks(pre_hooks=[user_hook]),
    )
    api.get_namespace("test-ns")

    user_hook.assert_called_once()


# --- Metrics ---


def test_prometheus_counter_increments(
    httpserver: HTTPServer, k8s_api: KubernetesApi
) -> None:
    """Test that Prometheus counter increments on API call."""
    httpserver.expect_request(
        "/api/v1/namespaces/test-ns",
    ).respond_with_json(k8s_namespace_json("test-ns"))

    counter_before = (
        REGISTRY.get_sample_value(
            "qontract_reconcile_external_api_kubernetes_requests_total",
            {"method": "namespaces.get", "verb": "GET"},
        )
        or 0.0
    )

    k8s_api.get_namespace("test-ns")

    counter_after = (
        REGISTRY.get_sample_value(
            "qontract_reconcile_external_api_kubernetes_requests_total",
            {"method": "namespaces.get", "verb": "GET"},
        )
        or 0.0
    )

    assert counter_after == counter_before + 1


def test_prometheus_histogram_observes(
    httpserver: HTTPServer, k8s_api: KubernetesApi
) -> None:
    """Test that Prometheus histogram records duration."""
    httpserver.expect_request(
        "/api/v1/namespaces/test-ns",
    ).respond_with_json(k8s_namespace_json("test-ns"))

    count_before = (
        REGISTRY.get_sample_value(
            "qontract_reconcile_external_api_kubernetes_request_duration_seconds_count",
            {"method": "namespaces.get", "verb": "GET"},
        )
        or 0.0
    )

    k8s_api.get_namespace("test-ns")

    count_after = (
        REGISTRY.get_sample_value(
            "qontract_reconcile_external_api_kubernetes_request_duration_seconds_count",
            {"method": "namespaces.get", "verb": "GET"},
        )
        or 0.0
    )

    assert count_after == count_before + 1


# --- Cleanup / Context Manager ---


def test_context_manager(httpserver: HTTPServer) -> None:
    """Test that KubernetesApi works as a context manager."""
    httpserver.expect_request(
        "/api/v1/namespaces/test-ns",
    ).respond_with_json(k8s_namespace_json("test-ns"))

    with KubernetesApi(
        server=httpserver.url_for(""),
        token="test-token",
    ) as api:
        ns = api.get_namespace("test-ns")
        assert ns.metadata is not None
        assert ns.metadata.name == "test-ns"


def test_close(httpserver: HTTPServer) -> None:
    """Test that close() can be called without error."""
    api = KubernetesApi(
        server=httpserver.url_for(""),
        token="test-token",
    )
    api.close()
