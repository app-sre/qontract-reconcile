"""Unit tests for GitlabProjectsService."""

from unittest.mock import MagicMock

import pytest
from qontract_utils.gitlab_api import GitlabGroup, GitlabProject

from qontract_api.integrations.gitlab_projects.domain import (
    GitlabGroupConfig,
    GitlabInstanceConfig,
    GitlabProjectConfig,
)
from qontract_api.integrations.gitlab_projects.schemas import (
    GitlabProjectAction,
    GitlabProjectActionCreate,
    GitlabProjectActionCreateSaasBundle,
)
from qontract_api.integrations.gitlab_projects.service import GitlabProjectsService
from qontract_api.models import Secret, TaskStatus

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_secret_manager() -> MagicMock:
    mock = MagicMock()
    mock.read.return_value = "test-token"
    return mock


@pytest.fixture
def mock_cache() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_settings() -> MagicMock:
    mock = MagicMock()
    mock.gitlab_projects.group_projects_cache_ttl = 300
    mock.gitlab_projects.api_timeout = 30
    return mock


@pytest.fixture
def mock_workspace_client() -> MagicMock:
    mock = MagicMock()
    mock.__enter__.return_value = mock
    mock.__exit__.return_value = None
    return mock


@pytest.fixture
def mock_workspace_client_factory(mock_workspace_client: MagicMock) -> MagicMock:
    return MagicMock(return_value=mock_workspace_client)


@pytest.fixture
def service(
    mock_secret_manager: MagicMock,
    mock_cache: MagicMock,
    mock_settings: MagicMock,
    mock_workspace_client_factory: MagicMock,
) -> GitlabProjectsService:
    return GitlabProjectsService(
        secret_manager=mock_secret_manager,
        cache=mock_cache,
        settings=mock_settings,
        workspace_client_factory=mock_workspace_client_factory,
    )


def _instance(
    name: str = "gitlab-cee",
    *,
    groups: list[GitlabGroupConfig] | None = None,
) -> GitlabInstanceConfig:
    return GitlabInstanceConfig(
        name=name,
        url=f"https://{name}.example.com",
        token=Secret(
            secret_manager_url="https://vault.example.com",
            path=f"secret/gitlab/{name}/token",
        ),
        groups=groups or [],
    )


def _project(name: str, *, is_saas_bundle: bool = False) -> GitlabProjectConfig:
    return GitlabProjectConfig(name=name, is_saas_bundle=is_saas_bundle)


def _group_cfg(
    group: str = "team", projects: list[GitlabProjectConfig] | None = None
) -> GitlabGroupConfig:
    return GitlabGroupConfig(group=group, projects=projects or [])


def _gitlab_group(
    group_id: int = 1, full_path: str = "team", project_names: list[str] | None = None
) -> GitlabGroup:
    return GitlabGroup(
        id=group_id, full_path=full_path, project_names=project_names or []
    )


def _gitlab_project(project_id: int = 1, name: str = "proj") -> GitlabProject:
    return GitlabProject(
        id=project_id, name=name, path_with_namespace=f"team/{name}", web_url="url"
    )


# ---------------------------------------------------------------------------
# _calculate_actions
# ---------------------------------------------------------------------------


def test_calculate_actions_creates_missing_project() -> None:
    actions = GitlabProjectsService._calculate_actions(
        "gitlab-cee", "team", [_project("foo")], existing_project_names=[]
    )

    assert len(actions) == 1
    assert isinstance(actions[0], GitlabProjectActionCreate)
    assert actions[0].project_name == "foo"
    assert actions[0].instance == "gitlab-cee"
    assert actions[0].group == "team"


def test_calculate_actions_skips_existing_project() -> None:
    actions = GitlabProjectsService._calculate_actions(
        "gitlab-cee", "team", [_project("foo")], existing_project_names=["foo"]
    )

    assert actions == []


def test_calculate_actions_ignores_removed_project() -> None:
    """This integration must never flag a project for deletion."""
    actions = GitlabProjectsService._calculate_actions(
        "gitlab-cee", "team", [], existing_project_names=["stale"]
    )

    assert actions == []


def test_calculate_actions_single_action_for_saas_bundle_project() -> None:
    actions = GitlabProjectsService._calculate_actions(
        "gitlab-cee",
        "team",
        [_project("bundle-repo", is_saas_bundle=True)],
        existing_project_names=[],
    )

    assert len(actions) == 1
    assert isinstance(actions[0], GitlabProjectActionCreateSaasBundle)
    assert actions[0].project_name == "bundle-repo"


def test_calculate_actions_no_bundle_init_for_plain_project() -> None:
    actions = GitlabProjectsService._calculate_actions(
        "gitlab-cee",
        "team",
        [_project("plain", is_saas_bundle=False)],
        existing_project_names=[],
    )

    assert len(actions) == 1
    assert isinstance(actions[0], GitlabProjectActionCreate)


def test_calculate_actions_deterministic_order() -> None:
    actions = GitlabProjectsService._calculate_actions(
        "gitlab-cee",
        "team",
        [_project("zzz"), _project("aaa")],
        existing_project_names=[],
    )

    assert [a.project_name for a in actions] == ["aaa", "zzz"]


# ---------------------------------------------------------------------------
# _apply_actions
# ---------------------------------------------------------------------------


def test_apply_actions_create_success(
    service: GitlabProjectsService, mock_workspace_client: MagicMock
) -> None:
    mock_workspace_client.create_project.return_value = _gitlab_project(
        project_id=42, name="foo"
    )
    actions: list[GitlabProjectAction] = [
        GitlabProjectActionCreate(instance="i", group="team", project_name="foo")
    ]

    applied, errors = service._apply_actions(mock_workspace_client, "i", 1, actions)

    assert applied == actions
    assert errors == []
    mock_workspace_client.create_project.assert_called_once_with("team", 1, "foo")


def test_apply_actions_create_saas_bundle_success(
    service: GitlabProjectsService, mock_workspace_client: MagicMock
) -> None:
    mock_workspace_client.create_project.return_value = _gitlab_project(
        project_id=42, name="bundle-repo"
    )
    actions: list[GitlabProjectAction] = [
        GitlabProjectActionCreateSaasBundle(
            instance="i", group="team", project_name="bundle-repo"
        ),
    ]

    applied, errors = service._apply_actions(mock_workspace_client, "i", 1, actions)

    assert applied == actions
    assert errors == []
    mock_workspace_client.initiate_saas_bundle_repo.assert_called_once_with(42)


def test_apply_actions_failed_create_reports_error_without_init(
    service: GitlabProjectsService, mock_workspace_client: MagicMock
) -> None:
    mock_workspace_client.create_project.side_effect = RuntimeError("boom")
    actions: list[GitlabProjectAction] = [
        GitlabProjectActionCreateSaasBundle(
            instance="i", group="team", project_name="bundle-repo"
        ),
    ]

    applied, errors = service._apply_actions(mock_workspace_client, "i", 1, actions)

    assert applied == []
    assert len(errors) == 1
    assert "boom" in errors[0]
    mock_workspace_client.initiate_saas_bundle_repo.assert_not_called()


def test_apply_actions_failed_saas_bundle_init_reports_error(
    service: GitlabProjectsService, mock_workspace_client: MagicMock
) -> None:
    mock_workspace_client.create_project.return_value = _gitlab_project(
        project_id=42, name="bundle-repo"
    )
    mock_workspace_client.initiate_saas_bundle_repo.side_effect = RuntimeError("boom")
    actions: list[GitlabProjectAction] = [
        GitlabProjectActionCreateSaasBundle(
            instance="i", group="team", project_name="bundle-repo"
        ),
    ]

    applied, errors = service._apply_actions(mock_workspace_client, "i", 1, actions)

    assert applied == []
    assert len(errors) == 1
    assert "boom" in errors[0]


def test_apply_actions_isolates_errors_across_projects(
    service: GitlabProjectsService, mock_workspace_client: MagicMock
) -> None:
    def create_side_effect(group: str, group_id: int, name: str) -> GitlabProject:
        if name == "bad":
            raise RuntimeError("boom")
        return _gitlab_project(project_id=1, name=name)

    mock_workspace_client.create_project.side_effect = create_side_effect
    actions: list[GitlabProjectAction] = [
        GitlabProjectActionCreate(instance="i", group="team", project_name="bad"),
        GitlabProjectActionCreate(instance="i", group="team", project_name="good"),
    ]

    applied, errors = service._apply_actions(mock_workspace_client, "i", 1, actions)

    assert [a.project_name for a in applied] == ["good"]
    assert len(errors) == 1


# ---------------------------------------------------------------------------
# reconcile — dry_run
# ---------------------------------------------------------------------------


def test_reconcile_dry_run_computes_actions_without_applying(
    service: GitlabProjectsService, mock_workspace_client: MagicMock
) -> None:
    mock_workspace_client.get_group.return_value = _gitlab_group()
    instances = [_instance(groups=[_group_cfg(projects=[_project("foo")])])]

    result = service.reconcile(instances, dry_run=True)

    assert result.status == TaskStatus.SUCCESS
    assert len(result.actions) == 1
    assert result.applied_actions == []
    assert result.applied_count == 0
    mock_workspace_client.create_project.assert_not_called()


def test_reconcile_non_dry_run_applies_actions(
    service: GitlabProjectsService, mock_workspace_client: MagicMock
) -> None:
    mock_workspace_client.get_group.return_value = _gitlab_group()
    mock_workspace_client.create_project.return_value = _gitlab_project(name="foo")
    instances = [_instance(groups=[_group_cfg(projects=[_project("foo")])])]

    result = service.reconcile(instances, dry_run=False)

    assert result.status == TaskStatus.SUCCESS
    assert result.applied_count == 1


# ---------------------------------------------------------------------------
# reconcile — error isolation
# ---------------------------------------------------------------------------


def test_reconcile_isolates_errors_across_groups(
    service: GitlabProjectsService, mock_workspace_client: MagicMock
) -> None:
    def get_group_side_effect(name: str) -> GitlabGroup:
        if name == "bad-group":
            raise RuntimeError("group not found")
        return _gitlab_group(full_path=name)

    mock_workspace_client.get_group.side_effect = get_group_side_effect
    instances = [
        _instance(
            groups=[
                _group_cfg(group="bad-group", projects=[_project("foo")]),
                _group_cfg(group="good-group", projects=[_project("bar")]),
            ]
        )
    ]

    result = service.reconcile(instances, dry_run=True)

    assert result.status == TaskStatus.FAILED
    assert len(result.errors) == 1
    assert "bad-group" in result.errors[0]
    # good-group must still be reconciled despite bad-group's failure
    assert any(a.project_name == "bar" for a in result.actions)


def test_reconcile_isolates_errors_across_instances(
    mock_secret_manager: MagicMock,
    mock_cache: MagicMock,
    mock_settings: MagicMock,
) -> None:
    good_client = MagicMock()
    good_client.__enter__.return_value = good_client
    good_client.__exit__.return_value = None
    good_client.get_group.return_value = _gitlab_group(project_names=["bar"])

    def factory(**kwargs: object) -> MagicMock:
        if kwargs["url"] == "https://bad-instance.example.com":
            raise RuntimeError("auth failed")
        return good_client

    service = GitlabProjectsService(
        secret_manager=mock_secret_manager,
        cache=mock_cache,
        settings=mock_settings,
        workspace_client_factory=factory,
    )
    instances = [
        _instance(name="bad-instance", groups=[_group_cfg(projects=[_project("foo")])]),
        _instance(
            name="good-instance", groups=[_group_cfg(projects=[_project("bar")])]
        ),
    ]

    result = service.reconcile(instances, dry_run=True)

    assert result.status == TaskStatus.FAILED
    assert len(result.errors) == 1
    assert "bad-instance" in result.errors[0]
    # good-instance must still be reconciled despite bad-instance's failure
    assert result.actions == []  # "bar" already exists per good_client's get_group


def test_reconcile_success_status_when_no_errors(
    service: GitlabProjectsService, mock_workspace_client: MagicMock
) -> None:
    mock_workspace_client.get_group.return_value = _gitlab_group()

    result = service.reconcile([_instance()], dry_run=True)

    assert result.status == TaskStatus.SUCCESS
    assert result.errors == []
