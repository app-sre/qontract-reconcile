"""Bookmark nullability for ldap-groups synthetic Celery task results."""

from unittest.mock import MagicMock, patch

from celery import states

from qontract_api.integrations.ldap_groups.schemas import LdapGroupsTaskResult
from qontract_api.models import TaskResult, TaskStatus
from qontract_api.tasks._utils import get_celery_task_result


@patch("qontract_api.tasks._utils.AsyncResult")
def test_dedup_skip_leaves_bookmark_unavailable(mock_async_result: MagicMock) -> None:
    skipped = TaskResult(
        status=TaskStatus.SKIPPED,
        errors=["duplicate"],
    )
    mock_async_result.return_value.state = states.SUCCESS
    mock_async_result.return_value.result = skipped

    result = get_celery_task_result("task-1", LdapGroupsTaskResult)

    assert result.status == TaskStatus.SUCCESS
    assert result.updated_managed_groups is None
    assert "Task skipped" in result.errors[0]


@patch("qontract_api.tasks._utils.AsyncResult")
def test_celery_failure_leaves_bookmark_unavailable(
    mock_async_result: MagicMock,
) -> None:
    mock_async_result.return_value.state = states.FAILURE
    mock_async_result.return_value.result = RuntimeError("worker lost")

    result = get_celery_task_result("task-2", LdapGroupsTaskResult)

    assert result.status == TaskStatus.FAILED
    assert result.updated_managed_groups is None
