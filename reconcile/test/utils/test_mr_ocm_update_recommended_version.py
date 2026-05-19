from unittest.mock import create_autospec

from gitlab.v4.objects import Project

from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.mr.ocm_update_recommended_version import (
    CreateOCMUpdateRecommendedVersion,
)

RAW_FILE = b"""\
---
name: ocm-production
recommendedVersions:
- channel: stable
  recommendedVersion: '4.12.0'
  workload: default
"""


def _make_mr() -> CreateOCMUpdateRecommendedVersion:
    mr = CreateOCMUpdateRecommendedVersion(
        ocm_name="ocm-production",
        path="data/ocm/production.yml",
        recommended_versions=[
            {"channel": "stable", "recommendedVersion": "4.13.0", "workload": "default"}
        ],
    )
    mr.branch = "test-branch"
    return mr


def test_process_updates_recommended_versions() -> None:
    cli = create_autospec(GitLabApi)
    cli.project = create_autospec(Project)
    cli.get_raw_file.return_value = RAW_FILE

    mr = _make_mr()
    mr.process(cli)

    cli.update_file.assert_called_once()
    call_kwargs = cli.update_file.call_args[1]
    content = call_kwargs["content"]
    assert "4.13.0" in content
    assert content.startswith("---\n")
    assert call_kwargs["branch_name"] == "test-branch"
    assert call_kwargs["file_path"] == "data/ocm/production.yml"
