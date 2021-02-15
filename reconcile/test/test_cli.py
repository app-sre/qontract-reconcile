from click.testing import CliRunner

import reconcile.cli as reconcile_cli


class TestCli:
    @staticmethod
    def test_config_is_required():
        runner = CliRunner()
        result = runner.invoke(reconcile_cli.integration)
        assert result.exit_code == 0
