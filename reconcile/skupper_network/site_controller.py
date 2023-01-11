import copy
from collections.abc import Mapping
from typing import Any

from reconcile.skupper_network.models import SkupperSite

LABELS = {"app": "skupper-site-controller", "managed-by": "qontract-reconcile"}
CONNECTION_TOKEN_LABELS = {"skupper.io/type": "connection-token"}
CONFIG_NAME = "skupper-site"


def site_config(site: SkupperSite) -> dict[str, Any]:
    """Skupper site configmap."""
    return dict(
        apiVersion="v1",
        kind="ConfigMap",
        metadata=dict(
            name=CONFIG_NAME,
            labels=LABELS,
        ),
        data=site.config.as_configmap_data(),
    )


def site_token(name: str, labels: Mapping[str, str]) -> dict[str, Any]:
    """Skupper site token secret."""
    _labels = copy.deepcopy(LABELS)
    _labels.update(labels)
    _labels["skupper.io/type"] = "connection-token-request"
    return dict(
        apiVersion="v1",
        kind="Secret",
        metadata=dict(
            name=name,
            labels=_labels,
        ),
    )


def site_controller_deployment(site: SkupperSite) -> dict[str, Any]:
    """Return skupper site controller deployment."""
    return dict(
        apiVersion="apps/v1",
        kind="Deployment",
        metadata=dict(
            name="skupper-site-controller",
            annotations={
                "kube-linter.io/ignore-all": "ignore",
            },
            labels=LABELS,
        ),
        spec=dict(
            replicas=1,
            selector=dict(
                matchLabels={"application": "skupper-site-controller"},
            ),
            template=dict(
                metadata=dict(
                    labels={"application": "skupper-site-controller"},
                ),
                spec=dict(
                    serviceAccountName="skupper-site-controller",
                    containers=[
                        dict(
                            name="site-controller",
                            image=site.skupper_site_controller,
                            env=[
                                dict(
                                    name="WATCH_NAMESPACE",
                                    valueFrom=dict(
                                        fieldRef=dict(
                                            fieldPath="metadata.namespace",
                                        ),
                                    ),
                                ),
                            ],
                        ),
                    ],
                ),
            ),
        ),
    )


def site_controller_service_account(
    site: SkupperSite,
) -> dict[str, Any]:
    """Skupper site controller service account."""
    return dict(
        apiVersion="v1",
        kind="ServiceAccount",
        metadata=dict(
            name="skupper-site-controller",
            labels=LABELS,
        ),
    )


def site_controller_role(site: SkupperSite) -> dict[str, Any]:
    """Skupper site controller role."""
    return dict(
        apiVersion="rbac.authorization.k8s.io/v1",
        kind="Role",
        metadata=dict(
            name="skupper-site-controller",
            labels=LABELS,
        ),
        rules=[
            dict(
                apiGroups=[""],
                resources=[
                    "configmaps",
                    "pods",
                    "pods/exec",
                    "services",
                    "secrets",
                    "serviceaccounts",
                ],
                verbs=["get", "list", "watch", "create", "update", "delete"],
            ),
            dict(
                apiGroups=["apps"],
                resources=["deployments", "statefulsets"],
                verbs=["get", "list", "watch", "create", "update", "delete"],
            ),
            dict(
                apiGroups=["apps"],
                resources=["daemonsets"],
                verbs=["get", "list", "watch"],
            ),
            dict(
                apiGroups=["route.openshift.io"],
                resources=["routes"],
                verbs=["get", "list", "watch", "create", "delete"],
            ),
            dict(
                apiGroups=["networking.k8s.io"],
                resources=["ingresses", "networkpolicies"],
                verbs=["get", "list", "watch", "create", "delete"],
            ),
            dict(
                apiGroups=["rbac.authorization.k8s.io"],
                resources=["rolebindings", "roles"],
                verbs=["get", "list", "watch", "create", "delete"],
            ),
        ],
    )


def site_controller_role_binding(site: SkupperSite) -> dict[str, Any]:
    """Skupper site controller role binding."""
    return dict(
        apiVersion="rbac.authorization.k8s.io/v1",
        kind="RoleBinding",
        metadata=dict(
            name="skupper-site-controller",
            labels=LABELS,
        ),
        roleRef=dict(
            apiGroup="rbac.authorization.k8s.io",
            kind="Role",
            name="skupper-site-controller",
        ),
        subjects=[
            dict(
                kind="ServiceAccount",
                name="skupper-site-controller",
            ),
        ],
    )


def is_usable_connection_token(secret: dict[str, Any]) -> bool:
    """Check if secret is a finished connection token, not a token-reqeust anymore."""
    # skupper changes the secret label from "connection-token-request" to "connection-token" when it is processed
    return secret.get("kind") == "Secret" and all(
        [
            secret["metadata"]["labels"][k] == v
            for k, v in CONNECTION_TOKEN_LABELS.items()
        ]
    )
