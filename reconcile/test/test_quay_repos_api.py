"""Tests for the quay-repos-api client-side integration."""

from __future__ import annotations

import pytest
from qontract_utils.exceptions import IntegrationError

from reconcile.gql_definitions.quay_repos_api.apps_quay_repos import (
    AppV1,
    QuayRepoItemV1,
    QuayRepoOrgInstanceV1,
    QuayRepoOrgV1,
    QuayRepoV1,
)
from reconcile.gql_definitions.quay_repos_api.quay_orgs import (
    QuayInstanceV1,
    QuayOrgV1,
    VaultSecretV1,
)
from reconcile.quay_repos_api import QuayReposIntegration, QuayReposIntegrationParams

SECRET_MANAGER_URL = "https://vault.example.com"


class _TestableIntegration(QuayReposIntegration):
    @property
    def secret_manager_url(self) -> str:
        return SECRET_MANAGER_URL


def _make_integration() -> _TestableIntegration:
    return _TestableIntegration(QuayReposIntegrationParams())


def _make_org(
    name: str = "myorg",
    instance_name: str = "quay.io",
    instance_url: str = "https://quay.io",
    managed_repos: bool = True,
    token_path: str = "secret/quay/myorg",
) -> QuayOrgV1:
    return QuayOrgV1(
        name=name,
        managedRepos=managed_repos,
        instance=QuayInstanceV1(name=instance_name, url=instance_url),
        automationToken=VaultSecretV1(path=token_path, field="token", version=None),
        mirror=None,
    )


def _make_app(org_name: str, instance_name: str, repo_names: list[str]) -> AppV1:
    return AppV1(
        quayRepos=[
            QuayRepoV1(
                org=QuayRepoOrgV1(
                    name=org_name,
                    instance=QuayRepoOrgInstanceV1(name=instance_name),
                ),
                items=[
                    QuayRepoItemV1(name=r, public=True, description="desc")
                    for r in repo_names
                ],
            )
        ]
    )


# ---------------------------------------------------------------------------
# compile_desired_state — duplicate repo name detection
# ---------------------------------------------------------------------------


def test_compile_desired_state_duplicate_repo_raises() -> None:
    integration = _make_integration()
    org = _make_org()
    app1 = _make_app("myorg", "quay.io", ["shared-repo"])
    app2 = _make_app("myorg", "quay.io", ["shared-repo"])

    with pytest.raises(IntegrationError, match="duplicate repo name"):
        integration.compile_desired_state(orgs=[org], apps=[app1, app2])


def test_compile_desired_state_duplicate_includes_org_context() -> None:
    integration = _make_integration()
    org = _make_org(name="myorg", instance_name="quay.io")
    app1 = _make_app("myorg", "quay.io", ["conflict"])
    app2 = _make_app("myorg", "quay.io", ["conflict"])

    with pytest.raises(IntegrationError, match=r"quay\.io/myorg"):
        integration.compile_desired_state(orgs=[org], apps=[app1, app2])


def test_compile_desired_state_no_duplicate_succeeds() -> None:
    integration = _make_integration()
    org = _make_org()
    app1 = _make_app("myorg", "quay.io", ["repo-a"])
    app2 = _make_app("myorg", "quay.io", ["repo-b"])

    result = integration.compile_desired_state(orgs=[org], apps=[app1, app2])
    assert len(result) == 1
    assert result[0].repos is not None
    repo_names = {r.name for r in result[0].repos}
    assert repo_names == {"repo-a", "repo-b"}


def test_compile_desired_state_duplicate_in_different_orgs_ok() -> None:
    integration = _make_integration()
    org1 = _make_org(name="org1", token_path="secret/quay/org1")
    org2 = _make_org(name="org2", token_path="secret/quay/org2")
    app1 = _make_app("org1", "quay.io", ["shared-name"])
    app2 = _make_app("org2", "quay.io", ["shared-name"])

    result = integration.compile_desired_state(orgs=[org1, org2], apps=[app1, app2])
    assert len(result) == 2
