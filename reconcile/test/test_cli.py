from typing import TYPE_CHECKING

import pytest
from click.testing import CliRunner

import reconcile.cli as reconcile_cli
from reconcile.gitlab_projects import (
    GitLabProjectsIntegration,
    GitlabProjectsIntegrationParams,
)

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


def test_config_is_required() -> None:
    runner = CliRunner()
    result = runner.invoke(reconcile_cli.integration, "--help")
    assert result.exit_code == 0


def test_parse_image_tag_from_ref_valid() -> None:
    t = ("env=main",)
    expected = {"env": "main"}
    result = reconcile_cli.parse_image_tag_from_ref(None, None, t)
    assert result == expected


def test_parse_image_tag_from_ref_invalid_1() -> None:
    t = ("env=",)
    with pytest.raises(SystemExit):
        reconcile_cli.parse_image_tag_from_ref(None, None, t)


def test_parse_image_tag_from_ref_invalid_2() -> None:
    t = ("=main",)
    with pytest.raises(SystemExit):
        reconcile_cli.parse_image_tag_from_ref(None, None, t)


def test_parse_image_tag_from_ref_invalid_3() -> None:
    t = ("=",)
    with pytest.raises(SystemExit):
        reconcile_cli.parse_image_tag_from_ref(None, None, t)


def test_parse_image_tag_from_ref_invalid_4() -> None:
    t = ("env=main=test",)
    with pytest.raises(SystemExit):
        reconcile_cli.parse_image_tag_from_ref(None, None, t)


@pytest.mark.parametrize(
    ("options", "instance_name", "project_names"),
    [
        ([], None, None),
        (
            [
                "--instance-name",
                "gitlab-cee",
                "--project-name",
                "foo",
                "--project-name",
                "bar",
            ],
            "gitlab-cee",
            frozenset({"foo", "bar"}),
        ),
    ],
)
def test_gitlab_projects_uses_api(
    mocker: MockerFixture,
    options: list[str],
    instance_name: str | None,
    project_names: frozenset[str] | None,
) -> None:
    run_integration = mocker.patch.object(reconcile_cli, "run_class_integration")

    result = CliRunner().invoke(
        reconcile_cli.integration.commands["gitlab-projects"], options
    )

    assert result.exit_code == 0
    run_integration.assert_called_once()
    integration = run_integration.call_args.kwargs["integration"]
    assert isinstance(integration, GitLabProjectsIntegration)
    assert integration.name == "gitlab-projects"
    assert integration.params == GitlabProjectsIntegrationParams(
        instance_name=instance_name, project_names=project_names
    )
    assert "gitlab-projects-api" not in reconcile_cli.integration.commands
