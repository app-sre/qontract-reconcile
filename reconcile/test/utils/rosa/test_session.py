from typing import Optional

import pytest

from reconcile.test.utils.rosa.conftest import ROSA_CLI_IMAGE
from reconcile.utils.jobcontroller.controller import K8sJobController
from reconcile.utils.jobcontroller.models import JobStatus
from reconcile.utils.rosa.rosa_cli import RosaCliException
from reconcile.utils.rosa.session import RosaSessionContextManager

#
# context manager
#


def test_rosa_session_ctx(rosa_session_ctx_manager: RosaSessionContextManager) -> None:
    with rosa_session_ctx_manager as rosa_session:
        assert not rosa_session.is_closed()
        assert rosa_session is not None
        assert rosa_session.aws_credentials is not None
        assert rosa_session.ocm_api is not None
    assert rosa_session.is_closed()


def test_rosa_session_ctx_exit(
    rosa_session_ctx_manager: RosaSessionContextManager,
) -> None:
    with pytest.raises(Exception):
        with rosa_session_ctx_manager as rosa_session:
            assert not rosa_session.is_closed()
            assert rosa_session is not None
            assert rosa_session.aws_credentials is not None
            assert rosa_session.ocm_api is not None
            raise Exception("boom!")
    assert rosa_session.is_closed()


def test_rosa_session_cli_execute(
    rosa_session_ctx_manager: RosaSessionContextManager,
) -> None:
    with rosa_session_ctx_manager as rosa_session:
        result = rosa_session.cli_execute("rosa whoami")
        assert result.status == JobStatus.SUCCESS


def test_rosa_session_cli_execute_fail(
    rosa_session_ctx_manager: RosaSessionContextManager,
    job_controller: K8sJobController,
) -> None:
    job_controller.enqueue_job_and_wait_for_completion.return_value = JobStatus.ERROR  # type: ignore[attr-defined]
    with rosa_session_ctx_manager as rosa_session:
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
    rosa_session_ctx_manager: RosaSessionContextManager,
) -> None:
    cmd = "rosa whoami"
    with rosa_session_ctx_manager as rosa_session:
        job = rosa_session.assemble_job(cmd, image_overwrite)
        assert job.cmd == rosa_session.wrap_cli_command(cmd)
        assert job.aws_credentials is not None
        assert job.ocm_token
        assert job.image == expected_image
