from typing import Any
from unittest.mock import (
    create_autospec,
    patch,
)

import pytest

from reconcile.gql_definitions.common.app_interface_vault_settings import (
    AppInterfaceSettingsV1,
)
from reconcile.openshift_resources_base import NAMESPACES_QUERY
from reconcile.prometheus_rules_tester.integration import Test as PTest
from reconcile.prometheus_rules_tester.integration import (
    check_rules_and_tests,
    run,
)
from reconcile.status import ExitCodes
from reconcile.utils import gql

from .fixtures import Fixtures

THREAD_POOL_SIZE = 2


class TstUnsupportedGqlQueryError(Exception):
    pass


class TestPrometheusRulesTester:
    def mock_gql_get_resource(self, path: str) -> dict[str, str]:
        """Mock for GqlApi.get_resources using fixtures. Namespace fixtures have paths
        that refer to files in fixture dir so that this methos loads them."""
        content = self.fxt.get(path)
        return {
            "path": path,
            "content": content,
            "sha256sum": "",
        }

    def mock_gql_query(self, query: str) -> dict[str, Any]:
        """Mock for GqlApi.query using test_data set in setup_method."""
        if query == NAMESPACES_QUERY:
            return {"namespaces": self.ns_data}

        raise TstUnsupportedGqlQueryError("Unsupported query")

    def setup_method(self) -> None:
        self.ns_data: dict[str, Any] = {}

        self.fxt = Fixtures("prometheus_rules_tester")
        self.alerting_services = {"yak-shaver"}
        self.vault_settings = AppInterfaceSettingsV1(vault=False)

        # Patcher for GqlApi methods
        self.gql_patcher = patch.object(gql, "get_api", autospec=True)
        self.gql = self.gql_patcher.start()
        gqlapi_mock = create_autospec(gql.GqlApi)
        self.gql.return_value = gqlapi_mock
        gqlapi_mock.query.side_effect = self.mock_gql_query
        gqlapi_mock.get_resource.side_effect = self.mock_gql_get_resource

    def teardown_method(self) -> None:
        """cleanup patches created in setup_method"""
        self.gql_patcher.stop()

    def run_check(self, cluster_name=None) -> list[PTest]:
        return check_rules_and_tests(
            vault_settings=self.vault_settings,
            alerting_services=self.alerting_services,
            thread_pool_size=THREAD_POOL_SIZE,
            cluster_name=cluster_name,
        )

    def test_ok_non_templated(self) -> None:
        self.ns_data = self.fxt.get_anymarkup("ns-ok-non-templated.yaml")
        assert self.run_check() == []

    def test_ok_templated(self) -> None:
        self.ns_data = self.fxt.get_anymarkup("ns-ok-templated.yaml")
        assert self.run_check() == []

    # Bad rule syntax should me caught by schema, but since we check it, we test it."
    def test_bad_rule(self) -> None:
        self.ns_data = self.fxt.get_anymarkup("ns-bad-rule.yaml")
        failed = self.run_check()
        assert len(failed) == 1
        assert "Error running promtool command" in str(failed[0].result)

    def test_bad_alerting_service(self) -> None:
        self.ns_data = self.fxt.get_anymarkup("ns-ok-templated.yaml")
        self.alerting_services = {"not-a-yak-shaver"}
        failed = self.run_check()
        assert len(failed) == 1
        assert "services are missing from alertingServices" in str(failed[0].result)

    @patch("reconcile.prometheus_rules_tester.integration.MAX_CONFIGMAP_SIZE", 1)
    def test_rule_too_long(self) -> None:
        self.ns_data = self.fxt.get_anymarkup("ns-ok-non-templated.yaml")
        failed = self.run_check()
        assert len(failed) == 1
        assert "Rules spec is larger than 1 bytes" in str(failed[0].result)

    def test_bad_test(self) -> None:
        self.ns_data = self.fxt.get_anymarkup("ns-bad-test.yaml")
        failed = self.run_check()
        assert len(failed) == 1
        assert "Error running promtool command" in str(failed[0].result)

    # Tests regarding filtering by cluster name.
    def test_2_ns_bad_alerting_service_unfiltered(self) -> None:
        self.ns_data = self.fxt.get_anymarkup("2-ns-ok-non-templated.yaml")
        self.alerting_services = {"not-a-yak-shaver"}
        assert len(self.run_check()) == 2

    def test_2_ns_bad_alerting_service_filtered(self) -> None:
        self.ns_data = self.fxt.get_anymarkup("2-ns-ok-non-templated.yaml")
        self.alerting_services = {"not-a-yak-shaver"}

        failed = self.run_check(cluster_name="appint-ex-01")
        assert len(failed) == 1

        failed = self.run_check(cluster_name="appint-ex-02")
        assert len(failed) == 1

        failed = self.run_check(cluster_name="no-such-cluster")
        assert len(failed) == 0

    @patch("reconcile.prometheus_rules_tester.integration.get_alerting_services")
    @patch(
        "reconcile.prometheus_rules_tester.integration.get_app_interface_vault_settings"
    )
    def test_run_logs_error(
        self, mocker_vault_settings, mocker_alerting_services, caplog
    ) -> None:
        self.ns_data = self.fxt.get_anymarkup("ns-bad-test.yaml")
        mocker_alerting_services.return_value = {"yak-shaver"}
        mocker_vault_settings.return_value = AppInterfaceSettingsV1(vault=False)
        cluster_name = "appint-ex-01"

        with pytest.raises(SystemExit) as exc:
            run(False, THREAD_POOL_SIZE, cluster_name=cluster_name)

        assert exc.value.code == ExitCodes.ERROR

        error_msg = (
            "Error checking rule bad-test.prometheusrules.yaml "
            "from namespace openshift-customer-monitoring in "
            f"cluster {cluster_name}: Error running promtool command"
        )
        assert error_msg in caplog.text
