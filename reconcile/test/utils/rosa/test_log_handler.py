import pytest

from reconcile.utils.rosa.rosa_cli import LogHandle

#
# LogHandler
#


@pytest.mark.parametrize(
    "max_lines, expected_lines",
    [
        (2, 2),
        (6, 5),
        (5, 5),
        (0, 0),
        (-1, 0),
    ],
)
def test_log_handle_get_log_lines(
    max_lines: int, expected_lines: int, log_handle: LogHandle
) -> None:
    lines = log_handle.get_log_lines(max_lines=max_lines)
    assert len(lines) == expected_lines
    for line in lines:
        assert not line.endswith("\n")


def test_log_handle_write_logs_to_logger(log_handle: LogHandle) -> None:
    content = ""

    def append(line: str) -> None:
        nonlocal content
        content += line

    log_handle.write_logs_to_logger(append)
    assert content.rstrip().split("\n") == log_handle.get_log_lines(5)


def test_log_handler_cleanup(log_handle: LogHandle) -> None:
    assert log_handle.exists()
    log_handle.cleanup()
    assert not log_handle.exists()
