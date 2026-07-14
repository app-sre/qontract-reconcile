"""Shared fixtures for Kubernetes API client tests."""

import pytest
from pytest_httpserver import HTTPServer
from qontract_utils.kubernetes.client import TIMEOUT, KubernetesApi


def k8s_namespace_json(name: str) -> dict:
    """Create a K8s Namespace JSON response."""
    return {
        "apiVersion": "v1",
        "kind": "Namespace",
        "metadata": {
            "name": name,
            "uid": f"uid-{name}",
            "creationTimestamp": "2024-01-01T00:00:00Z",
        },
        "status": {"phase": "Active"},
    }


def k8s_namespace_list_json(names: list[str]) -> dict:
    """Create a K8s NamespaceList JSON response."""
    return {
        "apiVersion": "v1",
        "kind": "NamespaceList",
        "metadata": {"resourceVersion": "1234"},
        "items": [k8s_namespace_json(name) for name in names],
    }


def k8s_project_json(name: str) -> dict:
    """Create an OpenShift Project JSON response."""
    return {
        "apiVersion": "project.openshift.io/v1",
        "kind": "Project",
        "metadata": {
            "name": name,
            "uid": f"uid-{name}",
            "creationTimestamp": "2024-01-01T00:00:00Z",
        },
        "status": {"phase": "Active"},
    }


def k8s_status_json(code: int, reason: str, message: str) -> dict:
    """Create a K8s Status error JSON response."""
    return {
        "apiVersion": "v1",
        "kind": "Status",
        "metadata": {},
        "status": "Failure",
        "message": message,
        "reason": reason,
        "code": code,
    }


def k8s_project_list_json(names: list[str]) -> dict:
    """Create an OpenShift ProjectList JSON response."""
    return {
        "apiVersion": "project.openshift.io/v1",
        "kind": "ProjectList",
        "metadata": {"resourceVersion": "1234"},
        "items": [k8s_project_json(name) for name in names],
    }


def mock_project_discovery(httpserver: HTTPServer) -> None:
    """Mock Project API discovery (list endpoint returns 200 with empty list)."""
    httpserver.expect_request(
        "/apis/project.openshift.io/v1/projects",
        method="GET",
    ).respond_with_json(k8s_project_list_json([]))


@pytest.fixture
def k8s_api(httpserver: HTTPServer) -> KubernetesApi:
    """Create a KubernetesApi connected to the test HTTP server (vanilla K8s)."""
    api = KubernetesApi(
        server=httpserver.url_for(""),
        token="test-token",
        timeout=TIMEOUT,
    )
    api._has_projects = False
    return api


@pytest.fixture
def k8s_api_openshift(httpserver: HTTPServer) -> KubernetesApi:
    """Create a KubernetesApi that detects OpenShift Project support."""
    mock_project_discovery(httpserver)
    api = KubernetesApi(
        server=httpserver.url_for(""),
        token="test-token",
        timeout=TIMEOUT,
    )
    api._supports_projects()
    return api
