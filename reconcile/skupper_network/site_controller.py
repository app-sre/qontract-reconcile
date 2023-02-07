import copy
from collections.abc import Mapping
from typing import Any

from reconcile.skupper_network.models import SkupperSite

LABELS = {"app": "skupper-site-controller", "managed-by": "qontract-reconcile"}
CONFIG_NAME = "skupper-site"


class SiteController:
    """Skupper site controller."""

    CONNECTION_TOKEN_LABELS = {"skupper.io/type": "connection-token"}

    def __init__(self, site: SkupperSite):
        self.site = site

    @property
    def resources(self) -> list[dict[str, Any]]:
        """Return the list of site-controller resources. Must be implemented by subclasses."""
        raise NotImplementedError()

    def is_usable_connection_token(self, secret: dict[str, Any]) -> bool:
        """Check if secret is a finished connection token, not a token-request anymore."""
        # skupper changes the secret label from "connection-token-request" to "connection-token" when it is processed
        return secret.get("kind") == "Secret" and all(
            secret.get("metadata", {}).get("labels", {}).get(k, None) == v
            for k, v in self.CONNECTION_TOKEN_LABELS.items()
        )

    def site_token(self, name: str, labels: Mapping[str, str]) -> dict[str, Any]:
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


class SiteControllerV1(SiteController):
    @property
    def resources(self) -> list[dict[str, Any]]:
        """Return the list of site-controller resources."""
        return [
            self.site_config(),
            self.site_controller_service_account(),
            self.site_controller_role(),
            self.site_controller_role_binding(),
            self.site_controller_deployment(),
        ]

    def site_config(self) -> dict[str, Any]:
        """Skupper site configmap."""
        return dict(
            apiVersion="v1",
            kind="ConfigMap",
            metadata=dict(
                name=CONFIG_NAME,
                labels=LABELS,
            ),
            data=self.site.config.as_configmap_data(),
        )

    def site_controller_deployment(self) -> dict[str, Any]:
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
                                image=self.site.skupper_site_controller,
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

    def site_controller_service_account(self) -> dict[str, Any]:
        """Skupper site controller service account."""
        return dict(
            apiVersion="v1",
            kind="ServiceAccount",
            metadata=dict(
                name="skupper-site-controller",
                labels=LABELS,
            ),
        )

    def site_controller_role(self) -> dict[str, Any]:
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

    def site_controller_role_binding(self) -> dict[str, Any]:
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


def get_site_controller(site: SkupperSite) -> SiteController:
    """Return the site controller."""
    skupper_version = site.skupper_site_controller.split(":")[1]
    if skupper_version.startswith("1."):
        return SiteControllerV1(site)
    raise NotImplementedError(f"Unsupported skupper version: {skupper_version}")
