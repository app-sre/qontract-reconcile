"""Unit tests for QuayReposService."""

from unittest.mock import MagicMock, patch

import pytest

from qontract_api.integrations.quay_repos.schemas import (
    QuayOrgConfig,
    QuayOrgKey,
    QuayRepoActionCreate,
    QuayRepoActionDelete,
    QuayRepoActionUpdateDescription,
    QuayRepoActionUpdateVisibility,
    QuayRepoConfig,
)
from qontract_api.integrations.quay_repos.service import (
    QuayReposConfigError,
    QuayReposService,
)
from qontract_api.models import Secret, TaskStatus
from qontract_utils.quay_api import QuayRepo


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_secret_manager() -> MagicMock:
    mock = MagicMock()
    mock.read.return_value = "test-token"
    return mock


@pytest.fixture
def service(mock_secret_manager: MagicMock) -> QuayReposService:
    return QuayReposService(secret_manager=mock_secret_manager)


def _org(
    instance: str = "quay.io",
    org_name: str = "myorg",
    managed_repos: bool = True,
    mirror: QuayOrgKey | None = None,
    repos: list[QuayRepoConfig] | None = None,
) -> QuayOrgConfig:
    return QuayOrgConfig(
        instance=instance,
        org_name=org_name,
        base_url=f"https://{instance}",
        automation_token=Secret(
            secret_manager_url="https://vault.example.com",
            path=f"secret/quay/{instance}/{org_name}",
        ),
        managed_repos=managed_repos,
        mirror=mirror,
        repos=repos or [],
    )


def _repo(name: str, public: bool = True, description: str = "") -> QuayRepoConfig:
    return QuayRepoConfig(name=name, public=public, description=description)


def _current_repo(name: str, is_public: bool = True, description: str = "") -> QuayRepo:
    return QuayRepo(name=name, is_public=is_public, description=description)


# ---------------------------------------------------------------------------
# _validate_org_configs
# ---------------------------------------------------------------------------


def test_validate_org_configs_valid_managed() -> None:
    orgs = [_org(managed_repos=True)]
    QuayReposService._validate_org_configs(orgs)  # No exception


def test_validate_org_configs_valid_mirror() -> None:
    upstream_key = QuayOrgKey(instance="quay.io", org_name="upstream")
    orgs = [
        _org(org_name="upstream", managed_repos=True),
        _org(org_name="mirror", managed_repos=False, mirror=upstream_key),
    ]
    QuayReposService._validate_org_configs(orgs)  # No exception


def test_validate_org_configs_mirror_and_managed_repos_raises() -> None:
    upstream_key = QuayOrgKey(instance="quay.io", org_name="upstream")
    orgs = [
        _org(org_name="upstream", managed_repos=True),
        _org(org_name="bad", managed_repos=True, mirror=upstream_key),
    ]
    with pytest.raises(QuayReposConfigError, match="both mirror and managed_repos"):
        QuayReposService._validate_org_configs(orgs)


def test_validate_org_configs_chained_mirror_raises() -> None:
    middle_key = QuayOrgKey(instance="quay.io", org_name="middle")
    upstream_key = QuayOrgKey(instance="quay.io", org_name="upstream")
    orgs = [
        _org(org_name="upstream", managed_repos=True),
        _org(org_name="middle", managed_repos=False, mirror=upstream_key),
        _org(org_name="leaf", managed_repos=False, mirror=middle_key),
    ]
    with pytest.raises(QuayReposConfigError, match="cannot have mirrors and be a mirror itself"):
        QuayReposService._validate_org_configs(orgs)


def test_validate_org_configs_empty_list() -> None:
    QuayReposService._validate_org_configs([])  # No exception


def test_org_config_duplicate_repo_names_raises() -> None:
    with pytest.raises(ValueError, match="duplicate repo names"):
        _org(repos=[_repo("myrepo"), _repo("myrepo")])


# ---------------------------------------------------------------------------
# _expand_desired_state
# ---------------------------------------------------------------------------


def test_expand_desired_state_skips_unmanaged_org(service: QuayReposService) -> None:
    orgs = [_org(managed_repos=False, mirror=None)]
    result = service._expand_desired_state(orgs)
    assert result == {}


def test_expand_desired_state_managed_org(service: QuayReposService) -> None:
    repo = _repo("myrepo")
    org = _org(managed_repos=True, repos=[repo])
    result = service._expand_desired_state([org])
    assert org.key in result
    assert result[org.key] == [repo]


def test_expand_desired_state_propagates_repos_to_mirror(service: QuayReposService) -> None:
    upstream = _org(org_name="upstream", managed_repos=True, repos=[_repo("shared")])
    mirror = _org(
        org_name="mirror",
        managed_repos=False,
        mirror=QuayOrgKey(instance="quay.io", org_name="upstream"),
    )
    result = service._expand_desired_state([upstream, mirror])
    assert mirror.key in result
    assert any(r.name == "shared" for r in result[mirror.key])


def test_expand_desired_state_mirror_org_own_repos(service: QuayReposService) -> None:
    upstream = _org(org_name="upstream", managed_repos=True, repos=[_repo("upstream-repo")])
    mirror = _org(
        org_name="mirror",
        managed_repos=False,
        mirror=QuayOrgKey(instance="quay.io", org_name="upstream"),
        repos=[_repo("mirror-only")],
    )
    result = service._expand_desired_state([upstream, mirror])
    mirror_repos = {r.name for r in result[mirror.key]}
    assert "upstream-repo" in mirror_repos
    assert "mirror-only" in mirror_repos


def test_expand_desired_state_empty_orgs(service: QuayReposService) -> None:
    assert service._expand_desired_state([]) == {}


# ---------------------------------------------------------------------------
# _calculate_actions
# ---------------------------------------------------------------------------


def test_calculate_actions_no_changes() -> None:
    org = _org()
    current = [_current_repo("repo1", is_public=True, description="desc")]
    desired = [_repo("repo1", public=True, description="desc")]
    actions = QuayReposService._calculate_actions(org, current, desired)
    assert actions == []


def test_calculate_actions_delete() -> None:
    org = _org()
    current = [_current_repo("old-repo")]
    desired: list[QuayRepoConfig] = []
    actions = QuayReposService._calculate_actions(org, current, desired)
    assert len(actions) == 1
    assert isinstance(actions[0], QuayRepoActionDelete)
    assert actions[0].repo_name == "old-repo"
    assert actions[0].instance == org.instance
    assert actions[0].org_name == org.org_name


def test_calculate_actions_create() -> None:
    org = _org()
    current: list[QuayRepo] = []
    desired = [_repo("new-repo", public=True, description="A new repo")]
    actions = QuayReposService._calculate_actions(org, current, desired)
    assert len(actions) == 1
    assert isinstance(actions[0], QuayRepoActionCreate)
    assert actions[0].repo_name == "new-repo"
    assert actions[0].public is True
    assert actions[0].description == "A new repo"


def test_calculate_actions_update_visibility() -> None:
    org = _org()
    current = [_current_repo("repo1", is_public=True)]
    desired = [_repo("repo1", public=False)]
    actions = QuayReposService._calculate_actions(org, current, desired)
    assert len(actions) == 1
    assert isinstance(actions[0], QuayRepoActionUpdateVisibility)
    assert actions[0].public is False


def test_calculate_actions_update_description() -> None:
    org = _org()
    current = [_current_repo("repo1", description="old")]
    desired = [_repo("repo1", description="new")]
    actions = QuayReposService._calculate_actions(org, current, desired)
    assert len(actions) == 1
    assert isinstance(actions[0], QuayRepoActionUpdateDescription)
    assert actions[0].description == "new"


def test_calculate_actions_update_both_visibility_and_description() -> None:
    org = _org()
    current = [_current_repo("repo1", is_public=True, description="old")]
    desired = [_repo("repo1", public=False, description="new")]
    actions = QuayReposService._calculate_actions(org, current, desired)
    assert len(actions) == 2
    types = {type(a) for a in actions}
    assert QuayRepoActionUpdateVisibility in types
    assert QuayRepoActionUpdateDescription in types


def test_calculate_actions_mixed() -> None:
    org = _org()
    current = [_current_repo("keep"), _current_repo("delete-me")]
    desired = [_repo("keep"), _repo("create-me")]
    actions = QuayReposService._calculate_actions(org, current, desired)
    action_types = {type(a) for a in actions}
    assert QuayRepoActionDelete in action_types
    assert QuayRepoActionCreate in action_types
    delete_action = next(a for a in actions if isinstance(a, QuayRepoActionDelete))
    assert delete_action.repo_name == "delete-me"
    create_action = next(a for a in actions if isinstance(a, QuayRepoActionCreate))
    assert create_action.repo_name == "create-me"


# ---------------------------------------------------------------------------
# reconcile() — dry_run=True
# ---------------------------------------------------------------------------


@patch("qontract_api.integrations.quay_repos.service.QuayApi")
def test_reconcile_dry_run_calculates_actions_only(
    mock_quay_api_cls: MagicMock,
    service: QuayReposService,
) -> None:
    mock_api = MagicMock()
    mock_api.list_images.return_value = []
    mock_quay_api_cls.return_value = mock_api

    org = _org(managed_repos=True, repos=[_repo("new-repo")])
    result = service.reconcile(orgs=[org], dry_run=True)

    assert result.status == TaskStatus.SUCCESS
    assert len(result.actions) == 1
    assert isinstance(result.actions[0], QuayRepoActionCreate)
    assert result.applied_actions == []
    assert result.applied_count == 0
    assert result.errors == []
    mock_api.repo_create.assert_not_called()


@patch("qontract_api.integrations.quay_repos.service.QuayApi")
def test_reconcile_dry_run_no_changes(
    mock_quay_api_cls: MagicMock,
    service: QuayReposService,
) -> None:
    mock_api = MagicMock()
    mock_api.list_images.return_value = [_current_repo("repo1")]
    mock_quay_api_cls.return_value = mock_api

    org = _org(managed_repos=True, repos=[_repo("repo1")])
    result = service.reconcile(orgs=[org], dry_run=True)

    assert result.status == TaskStatus.SUCCESS
    assert result.actions == []
    assert result.applied_count == 0


# ---------------------------------------------------------------------------
# reconcile() — dry_run=False
# ---------------------------------------------------------------------------


@patch("qontract_api.integrations.quay_repos.service.QuayApi")
def test_reconcile_apply_creates_repo(
    mock_quay_api_cls: MagicMock,
    service: QuayReposService,
) -> None:
    mock_api = MagicMock()
    mock_api.list_images.return_value = []
    mock_quay_api_cls.return_value = mock_api

    org = _org(managed_repos=True, repos=[_repo("new-repo", public=True, description="desc")])
    result = service.reconcile(orgs=[org], dry_run=False)

    assert result.status == TaskStatus.SUCCESS
    assert len(result.applied_actions) == 1
    assert result.applied_count == 1
    assert result.errors == []
    mock_api.repo_create.assert_called_once_with("new-repo", "desc", True)


@patch("qontract_api.integrations.quay_repos.service.QuayApi")
def test_reconcile_apply_deletes_repo(
    mock_quay_api_cls: MagicMock,
    service: QuayReposService,
) -> None:
    mock_api = MagicMock()
    mock_api.list_images.return_value = [_current_repo("stale")]
    mock_quay_api_cls.return_value = mock_api

    org = _org(managed_repos=True, repos=[])
    result = service.reconcile(orgs=[org], dry_run=False)

    assert result.status == TaskStatus.SUCCESS
    assert result.applied_count == 1
    mock_api.repo_delete.assert_called_once_with("stale")


@patch("qontract_api.integrations.quay_repos.service.QuayApi")
def test_reconcile_apply_makes_repo_private(
    mock_quay_api_cls: MagicMock,
    service: QuayReposService,
) -> None:
    mock_api = MagicMock()
    mock_api.list_images.return_value = [_current_repo("repo1", is_public=True)]
    mock_quay_api_cls.return_value = mock_api

    org = _org(managed_repos=True, repos=[_repo("repo1", public=False)])
    result = service.reconcile(orgs=[org], dry_run=False)

    assert result.status == TaskStatus.SUCCESS
    mock_api.repo_make_private.assert_called_once_with("repo1")
    mock_api.repo_make_public.assert_not_called()


@patch("qontract_api.integrations.quay_repos.service.QuayApi")
def test_reconcile_apply_makes_repo_public(
    mock_quay_api_cls: MagicMock,
    service: QuayReposService,
) -> None:
    mock_api = MagicMock()
    mock_api.list_images.return_value = [_current_repo("repo1", is_public=False)]
    mock_quay_api_cls.return_value = mock_api

    org = _org(managed_repos=True, repos=[_repo("repo1", public=True)])
    result = service.reconcile(orgs=[org], dry_run=False)

    assert result.status == TaskStatus.SUCCESS
    mock_api.repo_make_public.assert_called_once_with("repo1")
    mock_api.repo_make_private.assert_not_called()


@patch("qontract_api.integrations.quay_repos.service.QuayApi")
def test_reconcile_apply_updates_description(
    mock_quay_api_cls: MagicMock,
    service: QuayReposService,
) -> None:
    mock_api = MagicMock()
    mock_api.list_images.return_value = [_current_repo("repo1", description="old")]
    mock_quay_api_cls.return_value = mock_api

    org = _org(managed_repos=True, repos=[_repo("repo1", description="new")])
    result = service.reconcile(orgs=[org], dry_run=False)

    assert result.status == TaskStatus.SUCCESS
    mock_api.repo_update_description.assert_called_once_with("repo1", "new")


# ---------------------------------------------------------------------------
# reconcile() — error handling
# ---------------------------------------------------------------------------


@patch("qontract_api.integrations.quay_repos.service.QuayApi")
def test_reconcile_per_org_exception_captured(
    mock_quay_api_cls: MagicMock,
    service: QuayReposService,
) -> None:
    mock_quay_api_cls.side_effect = Exception("Network error")

    org = _org(managed_repos=True, repos=[_repo("repo1")])
    result = service.reconcile(orgs=[org], dry_run=True)

    assert result.status == TaskStatus.FAILED
    assert len(result.errors) == 1
    assert "quay.io/myorg" in result.errors[0]
    assert "Network error" in result.errors[0]
    assert result.actions == []


@patch("qontract_api.integrations.quay_repos.service.QuayApi")
def test_reconcile_per_action_exception_captured(
    mock_quay_api_cls: MagicMock,
    service: QuayReposService,
) -> None:
    mock_api = MagicMock()
    mock_api.list_images.return_value = []
    mock_api.repo_create.side_effect = Exception("Quay API 500")
    mock_quay_api_cls.return_value = mock_api

    org = _org(managed_repos=True, repos=[_repo("new-repo")])
    result = service.reconcile(orgs=[org], dry_run=False)

    assert result.status == TaskStatus.FAILED
    assert len(result.errors) == 1
    assert "create" in result.errors[0]
    assert "Quay API 500" in result.errors[0]
    assert len(result.actions) == 1  # action was generated
    assert result.applied_count == 0  # but not applied


def test_reconcile_config_error_propagates(service: QuayReposService) -> None:
    upstream_key = QuayOrgKey(instance="quay.io", org_name="upstream")
    orgs = [
        _org(org_name="upstream", managed_repos=True),
        _org(org_name="bad", managed_repos=True, mirror=upstream_key),
    ]
    with pytest.raises(QuayReposConfigError):
        service.reconcile(orgs=orgs)


@patch("qontract_api.integrations.quay_repos.service.QuayApi")
def test_reconcile_multiple_orgs_partial_failure(
    mock_quay_api_cls: MagicMock,
    service: QuayReposService,
    mock_secret_manager: MagicMock,
) -> None:
    good_api = MagicMock()
    good_api.list_images.return_value = []

    call_count = 0

    def api_factory(**_kwargs: object) -> MagicMock:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise Exception("first org failed")
        return good_api

    mock_quay_api_cls.side_effect = api_factory

    orgs = [
        _org(org_name="org1", managed_repos=True, repos=[_repo("r1")]),
        _org(org_name="org2", managed_repos=True, repos=[_repo("r2")]),
    ]
    result = service.reconcile(orgs=orgs, dry_run=True)

    assert result.status == TaskStatus.FAILED
    assert len(result.errors) == 1
    assert "org1" in result.errors[0]
    assert len(result.actions) == 1  # org2 succeeded
