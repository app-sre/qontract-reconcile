from unittest.mock import create_autospec

import pytest
from gitlab.v4.objects import Project

from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.mr.base import CancelMergeRequestError
from reconcile.utils.mr.ocm_upgrade_scheduler_org_updates import (
    CreateOCMUpgradeSchedulerOrgUpdates,
)

RAW_FILE = b"""\
---
name: ocm-production
upgradePolicyClusters:
- name: existing-cluster
  serverUrl: https://existing.example.com
  spec:
    id: existing-id
  upgradePolicy:
    schedule_type: manual
"""


def _make_mr_add() -> CreateOCMUpgradeSchedulerOrgUpdates:
    mr = CreateOCMUpgradeSchedulerOrgUpdates(
        updates_info={
            "name": "ocm-production",
            "path": "data/ocm/production.yml",
            "updates": [
                {
                    "action": "add",
                    "cluster": "new-cluster",
                    "id": "new-id",
                    "url": "https://new.example.com",
                    "policy": {"schedule_type": "manual"},
                }
            ],
        }
    )
    mr.branch = "test-branch"
    return mr


def _make_mr_delete() -> CreateOCMUpgradeSchedulerOrgUpdates:
    mr = CreateOCMUpgradeSchedulerOrgUpdates(
        updates_info={
            "name": "ocm-production",
            "path": "data/ocm/production.yml",
            "updates": [
                {
                    "action": "delete",
                    "cluster": "existing-cluster",
                }
            ],
        }
    )
    mr.branch = "test-branch"
    return mr


def test_process_add_cluster() -> None:
    cli = create_autospec(GitLabApi)
    cli.project = create_autospec(Project)
    cli.get_raw_file.return_value = RAW_FILE

    mr = _make_mr_add()
    mr.process(cli)

    cli.update_file.assert_called_once()
    call_kwargs = cli.update_file.call_args[1]
    content = call_kwargs["content"]
    assert "new-cluster" in content
    assert "existing-cluster" in content
    assert content.startswith("---\n")


def test_process_delete_cluster() -> None:
    cli = create_autospec(GitLabApi)
    cli.project = create_autospec(Project)
    cli.get_raw_file.return_value = RAW_FILE

    mr = _make_mr_delete()
    mr.process(cli)

    cli.update_file.assert_called_once()
    call_kwargs = cli.update_file.call_args[1]
    content = call_kwargs["content"]
    assert "existing-cluster" not in content
    assert content.startswith("---\n")


def test_process_no_changes_cancels() -> None:
    cli = create_autospec(GitLabApi)
    cli.project = create_autospec(Project)
    cli.get_raw_file.return_value = RAW_FILE

    mr = CreateOCMUpgradeSchedulerOrgUpdates(
        updates_info={
            "name": "ocm-production",
            "path": "data/ocm/production.yml",
            "updates": [
                {
                    "action": "add",
                    "cluster": "existing-cluster",
                    "id": "existing-id",
                    "url": "https://existing.example.com",
                    "policy": {"schedule_type": "manual"},
                }
            ],
        }
    )
    mr.branch = "test-branch"

    with pytest.raises(CancelMergeRequestError):
        mr.process(cli)


def test_process_unsupported_action_raises() -> None:
    cli = create_autospec(GitLabApi)
    cli.project = create_autospec(Project)
    cli.get_raw_file.return_value = RAW_FILE

    mr = CreateOCMUpgradeSchedulerOrgUpdates(
        updates_info={
            "name": "ocm-production",
            "path": "data/ocm/production.yml",
            "updates": [
                {
                    "action": "unknown",
                    "cluster": "some-cluster",
                }
            ],
        }
    )
    mr.branch = "test-branch"

    with pytest.raises(NotImplementedError):
        mr.process(cli)
