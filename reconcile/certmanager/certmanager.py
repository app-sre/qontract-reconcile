from typing import Any, Mapping

from reconcile.utils.unleash import (
    get_feature_toggle_state,
    get_feature_toggle_strategies,
)

CERT_UTILS_SECRET_SYNC_ANNOTATION = (
    "cert-utils-operator.redhat-cop.io/certs-from-secret"
)

CERT_MANAGER_ISSUER_ANNOTATION = "cert-manager.io/issuer"
CERT_MANAGER_CLUSTER_ISSUER_ANNOTATION = "cert-manager.io/cluster-issuer"
CERT_MANAGER_CERTIFICATE_CRD = "Certificate.cert-manager.io"

CERT_MANAGER_DEFAULT_ISSUER_NAME = "default-http"
CERT_MANAGER_DEFAULT_ISSUER_TYPE = "ClusterIssuer"

UNLEASH_CERT_MANAGER_FEATURE_TOOGLE = "cert-manager-routes"


def build_certificate(
    name: str,
    hosts: list[str],
    secretName: str,
    issuer: str = "default-http",
    issuer_type: str = "ClusterIssuer",
) -> dict[str, Any]:

    metadata = {}
    spec: dict[str, Any] = {
        "issuerRef": {"name": issuer, "kind": issuer_type, "group": "cert-manager.io"}
    }
    metadata["name"] = name
    spec["dnsNames"] = hosts
    spec["secretName"] = secretName

    cert: dict[str, Any] = {}
    cert["apiVersion"] = "cert-manager.io/v1"
    cert["kind"] = "Certificate"
    cert["metadata"] = metadata
    cert["spec"] = spec
    return cert


def build_certificate_from_route(route: Mapping[str, Any]) -> dict[str, Any]:
    metadata = route["metadata"]
    annotations = metadata["annotations"]
    a_issuer = annotations.get(CERT_MANAGER_ISSUER_ANNOTATION)
    a_cluster_issuer = annotations.get(CERT_MANAGER_CLUSTER_ISSUER_ANNOTATION)

    issuer = CERT_MANAGER_DEFAULT_ISSUER_NAME
    issuer_type = CERT_MANAGER_DEFAULT_ISSUER_TYPE

    if a_issuer:
        issuer_type = "Issuer"
        issuer = a_issuer

    if a_cluster_issuer:
        issuer_type = "ClusterIssuer"
        issuer = a_cluster_issuer

    cert_name = metadata["name"] + "-cert"
    secret_name = cert_name + "-secret"

    cert = build_certificate(
        cert_name, [route["spec"]["host"]], secret_name, issuer, issuer_type
    )
    return cert


def route_needs_certificate(route: Mapping[str, Any]) -> bool:
    annotations = route["metadata"]["annotations"]
    tls_acme = annotations.get("kubernetes.io/tls-acme")
    if not tls_acme or tls_acme != "true":
        return False
    else:
        return True


def unleash_post_process_route_enabled(cluster: str, namespace: str):
    strategies = get_feature_toggle_strategies(
        UNLEASH_CERT_MANAGER_FEATURE_TOOGLE, ["perClusterNamespace"]
    )
    post_process = False
    key = f"{cluster}/{namespace}"
    if strategies:
        for s in strategies:
            if key in s.parameters["cluster_namespace"].split(","):
                post_process = True
                break

    if post_process and get_feature_toggle_state(UNLEASH_CERT_MANAGER_FEATURE_TOOGLE):
        return True
