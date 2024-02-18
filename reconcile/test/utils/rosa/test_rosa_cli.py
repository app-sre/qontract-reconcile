from typing import Any

import pytest

from reconcile.utils.rosa.rosa_cli import RosaJob


@pytest.mark.parametrize(
    "change, expect_identity_to_change",
    [
        ({"cmd": "other cmd"}, True),
        ({"aws_account_id": "another-account-id"}, True),
        ({"aws_region": "another-region"}, True),
        ({"ocm_org_id": "another-token"}, False),
        ({"service_account": "another-sa"}, True),
        ({"image": "another_image:latest"}, True),
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
        "OCM_TOKEN",
    }


def test_rosa_job_spec(rosa_job: RosaJob) -> None:
    job_spec = rosa_job.job_spec()
    container = job_spec.template.spec.containers[0]  # type: ignore
    assert container.image == rosa_job.image
    assert container.args == [rosa_job.cmd]
    assert {e.name for e in container.env or []} == {
        "AWS_SHARED_CREDENTIALS_FILE",
        "AWS_REGION",
        "OCM_TOKEN",
    }
