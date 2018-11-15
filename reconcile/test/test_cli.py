from click.testing import CliRunner

import reconcile.cli as reconcile_cli


class TestCli(object):
    def test_config_is_required(self):
        runner = CliRunner()
        result = runner.invoke(reconcile_cli.main)
        assert result.exit_code != 0
