import pytest

from reconcile.utils.jobcontroller.controller import K8sJobController
from reconcile.utils.jobcontroller.models import JobStatus
from reconcile.utils.rosa.rosa_cli import RosaCliException
from reconcile.utils.rosa.session import RosaSessionContextManager


def test_rosa_session_ctx(rosa_session_ctx_manager: RosaSessionContextManager) -> None:
    with rosa_session_ctx_manager as rosa_session:
        assert not rosa_session.is_closed()
        assert rosa_session is not None
        assert rosa_session.aws_session_builder is not None
        assert rosa_session.ocm_api is not None
    assert rosa_session.is_closed()


def test_rosa_session_ctx_exit(
    rosa_session_ctx_manager: RosaSessionContextManager,
) -> None:
    with pytest.raises(Exception):
        with rosa_session_ctx_manager as rosa_session:
            assert not rosa_session.is_closed()
            assert rosa_session is not None
            assert rosa_session.aws_session_builder is not None
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
