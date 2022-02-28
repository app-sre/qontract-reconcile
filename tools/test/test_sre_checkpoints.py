from unittest.mock import patch

# from reconcile import queries
from tools.sre_checkpoints import full_name, get_latest_sre_checkpoints
from tools.qontract_cli import sre_checkpoints


class TestFullName:
    @staticmethod
    def test_with_parent():
        app = {
            "parentApp": {"name": "app1"},
            "name": "app2",
        }
        assert full_name(app) == "app1/app2"

    @staticmethod
    def test_without_parent():
        app = {
            "name": "app2",
        }
        assert full_name(app) == "app2"


class TestLatestSRECheckpoints:
    @staticmethod
    @patch("reconcile.queries.get_sre_checkpoints")
    def test_latest(get_sre_checkpoints):
        get_sre_checkpoints.return_value = [
            {"date": "2020-01-01", "app": {"name": "app_single"}},
            {"date": "2021-01-01", "app": {"name": "app_single"}},
            {"date": "2020-03-01", "app": {"name": "app_single"}},
            {
                "date": "2020-01-02",
                "app": {"parentApp": {"name": "app1"}, "name": "app2"},
            },
        ]

        latest_sre_checkpoints = get_latest_sre_checkpoints()
        assert latest_sre_checkpoints["app_single"] == "2021-01-01"
        assert latest_sre_checkpoints["app1/app2"] == "2020-01-02"


class TestGetSRECheckpoints:
    @staticmethod
    @patch("tools.qontract_cli.print_output")
    @patch("reconcile.queries.get_sre_checkpoints")
    @patch("reconcile.queries.get_apps")
    def test_sre_checkpoints(get_apps, get_sre_checkpoints, print_output):
        get_apps.return_value = [
            {"name": "app1", "path": "/app1", "onboardingStatus": "OnBoarded"},
            {"name": "app2", "path": "/app2", "onboardingStatus": "OnBoarded"},
            {"name": "app3", "path": "/app3", "onboardingStatus": "OnBoarded"},
            {"name": "app4", "path": "/app4", "onboardingStatus": "InProgress"},
        ]

        get_sre_checkpoints.return_value = [
            {"app": {"name": "app1"}, "date": "2021-01-02"},
            {"app": {"name": "app1"}, "date": "2021-01-01"},
        ]

        expected_data = [
            {"name": "app1", "latest": "2021-01-02"},
            {"name": "app2", "latest": ""},
            {"name": "app3", "latest": ""},
        ]

        with sre_checkpoints.make_context(info_name="info", args=[]) as ctx:
            ctx.obj = {"options": {"output": "json"}}
            sre_checkpoints.invoke(ctx)

            cols = ["name", "latest"]
            print_output.assert_called_once_with(
                {"output": "json"}, expected_data, cols
            )
