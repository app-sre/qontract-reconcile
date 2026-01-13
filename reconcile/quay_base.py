from collections import UserDict, namedtuple
from typing import Any, TypedDict

from reconcile import queries
from reconcile.utils.quay_api import QuayApi
from reconcile.utils.secret_reader import SecretReader

OrgKey = namedtuple("OrgKey", ["instance", "org_name"])


class OrgInfo(TypedDict):
    url: str
    push_token: dict[str, str] | None
    teams: list[str]
    managedRepos: bool
    mirror: OrgKey | None
    mirror_filters: dict[str, Any]
    api: QuayApi


class QuayApiStore(UserDict[OrgKey, OrgInfo]):
    def __init__(self) -> None:
        super().__init__(get_quay_api_store())

    def cleanup(self) -> None:
        """Close all QuayApi sessions."""
        for org_info in self.data.values():
            org_info["api"].cleanup()

    def __enter__(self) -> "QuayApiStore":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.cleanup()


def get_quay_api_store() -> dict[OrgKey, OrgInfo]:
    """
    Returns a dictionary with a key for each Quay organization
    managed in app-interface.
    """
    quay_orgs = queries.get_quay_orgs()
    settings = queries.get_app_interface_settings()
    secret_reader = SecretReader(settings=settings)
    store = {}
    for org_data in quay_orgs:
        instance_name = org_data["instance"]["name"]
        org_name = org_data["name"]
        org_key = OrgKey(instance_name, org_name)
        base_url = org_data["instance"]["url"]
        automation_token = org_data["automationToken"]
        if not automation_token:
            continue
        token = secret_reader.read(automation_token)

        if org_data.get("mirror"):
            mirror = OrgKey(
                org_data["mirror"]["instance"]["name"], org_data["mirror"]["name"]
            )
        else:
            mirror = None

        mirror_filters = {}
        if org_data.get("mirrorFilters"):
            for repo in org_data["mirrorFilters"]:
                mirror_filters[repo["name"]] = {
                    "tags": repo.get("tags"),
                    "tags_exclude": repo.get("tagsExclude"),
                }

        if org_data.get("pushCredentials"):
            push_token = secret_reader.read_all(org_data["pushCredentials"])
        else:
            push_token = None

        # Create QuayApi instance for this org
        api = QuayApi(
            token=token,
            organization=org_name,
            base_url=base_url,
        )

        org_info: OrgInfo = {
            "url": base_url,
            "push_token": push_token,
            "teams": org_data.get("managedTeams") or [],
            "managedRepos": bool(org_data.get("managedRepos")),
            "mirror": mirror,
            "mirror_filters": mirror_filters,
            "api": api,
        }

        store[org_key] = org_info

    return store
