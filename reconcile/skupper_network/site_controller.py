import copy
from collections.abc import MutableMapping
from typing import Any

from reconcile.skupper_network.models import SkupperSite


class SiteController:
    """Skupper site controller."""

    CONNECTION_TOKEN_LABELS = {"skupper.io/type": "connection-token"}

    def __init__(self, site: SkupperSite):
        self.site = site

    @property
    def resources(self) -> list[dict[str, Any]]:
        """Return the list of site-controller resources."""
        return self.site.site_controller_objects

    def is_usable_connection_token(self, secret: dict[str, Any]) -> bool:
        """Check if secret is a finished connection token, not a token-request anymore."""
        # skupper changes the secret label from "connection-token-request" to "connection-token" when it is processed
        return secret.get("kind") == "Secret" and all(
            secret.get("metadata", {}).get("labels", {}).get(k, None) == v
            for k, v in self.CONNECTION_TOKEN_LABELS.items()
        )

    def site_token(self, name: str, labels: MutableMapping[str, str]) -> dict[str, Any]:
        """Skupper site token secret."""
        labels_ = copy.deepcopy(labels)
        labels_["skupper.io/type"] = "connection-token-request"
        return {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {
                "name": name,
                "labels": labels_,
            },
        }


def get_site_controller(site: SkupperSite) -> SiteController:
    """Return the site controller."""
    return SiteController(site)
