import pytest

from tools.cli_commands.cost_report import CostReportCommand


def test_cost_report_create() -> None:
    cost_report_command = CostReportCommand.create()
    assert isinstance(cost_report_command, CostReportCommand)


@pytest.fixture
def cost_report_command() -> CostReportCommand:
    return CostReportCommand.create()


def test_cost_report_execute(cost_report_command: CostReportCommand) -> None:
    assert cost_report_command.execute() is None
