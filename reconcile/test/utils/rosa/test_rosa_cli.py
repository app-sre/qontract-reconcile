from typing import Any

import pytest

from reconcile.utils.rosa.rosa_cli import RosaJob


@pytest.mark.parametrize(
    "change, expect_identity_to_change",
    [
        ({"cmd": "other cmd"}, True),
        ({"account_name": "another_account"}, True),
        ({"cluster_name": "another_cluster"}, True),
        ({"org_id": "123"}, True),
        ({"dry_run": True}, True),
        ({"image": "another_image:latest"}, True),
        ({"aws_credentials": {"access_key_id": "another_access_key"}}, False),
        ({"ocm_token": "another_ocm_token"}, False),
    ],
)
def test_rosa_job_identity(
    change: dict[str, Any], expect_identity_to_change: bool, rosa_job: RosaJob
) -> None:
    other_job = rosa_job.copy(deep=True, update=change)
    identity_digest_changed = (
        rosa_job.unit_of_work_digest() != other_job.unit_of_work_digest()
    )
    assert identity_digest_changed == expect_identity_to_change


def test_rosa_job_secret_data(rosa_job: RosaJob) -> None:
    secret_data = rosa_job.secret_data()
    assert set(secret_data.keys()) == {
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_REGION",
        "OCM_TOKEN",
    }


def test_rosa_job_spec(rosa_job: RosaJob) -> None:
    job_spec = rosa_job.job_spec()
    container = job_spec.template.spec.containers[0]  # type: ignore
    assert container.image == rosa_job.image
    assert container.args == [rosa_job.cmd]
    assert {e.name for e in container.env or []} == {
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_REGION",
        "OCM_TOKEN",
    }
