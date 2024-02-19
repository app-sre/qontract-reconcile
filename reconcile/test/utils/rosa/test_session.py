from typing import Optional

import pytest

from reconcile.test.utils.rosa.conftest import ROSA_CLI_IMAGE
from reconcile.utils.jobcontroller.controller import K8sJobController
from reconcile.utils.jobcontroller.models import JobStatus
from reconcile.utils.rosa.rosa_cli import RosaCliException
from reconcile.utils.rosa.session import RosaSession

#
# context manager
#


def test_rosa_session_cli_execute(
    rosa_session: RosaSession,
) -> None:
    result = rosa_session.cli_execute("rosa whoami")
    assert result.status == JobStatus.SUCCESS


def test_rosa_session_cli_execute_fail(
    rosa_session: RosaSession,
    job_controller: K8sJobController,
) -> None:
    job_controller.enqueue_job_and_wait_for_completion.return_value = JobStatus.ERROR  # type: ignore[attr-defined]
    with pytest.raises(RosaCliException):
        rosa_session.cli_execute("rosa whoami")


#
# assemble job
#


@pytest.mark.parametrize(
    "image_overwrite, expected_image",
    [(None, ROSA_CLI_IMAGE), ("my_image:latest", "my_image:latest")],
)
def test_assemble_job_image_override(
    image_overwrite: Optional[str],
    expected_image: str,
    rosa_session: RosaSession,
) -> None:
    cmd = "rosa whoami"
    job = rosa_session.assemble_job(cmd=cmd, image=image_overwrite)
    assert job.cmd == rosa_session.wrap_cli_command(cmd)
    assert job.ocm_token
    assert job.image == expected_image
