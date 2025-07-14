from collections.abc import Mapping
from typing import Any
from unittest import TestCase
from unittest.mock import (
    Mock,
    call,
    patch,
)

import reconcile.ocm_additional_routers as integ
from reconcile import queries
from reconcile.utils.ocm import OCMMap

from .fixtures import Fixtures

fxt = Fixtures("ocm_additional_routers")


class TestOCMAdditionalRouters(TestCase):
    # integration test
    @patch.object(queries, "get_clusters")
    def test_integ_fail(self, get_clusters: Mock) -> None:
        fixture = fxt.get_anymarkup("state.yml")

        clusters = fixture["gql_response"]
        for c in clusters:
            c.pop("additionalRouters")
        get_clusters.return_value = clusters

        with self.assertRaises(SystemExit):
            integ.run(False)

    @patch.object(queries, "get_app_interface_settings")
    @patch.object(queries, "get_clusters")
    @patch.object(OCMMap, "init_ocm_client_from_cluster")
    @patch.object(OCMMap, "get")
    def test_integ(
        self,
        get: Mock,
        init_ocm_client_from_cluster: Mock,
        get_clusters: Mock,
        get_app_interface_settings: Mock,
    ) -> None:
        fixture = fxt.get_anymarkup("state.yml")

        get_clusters.return_value = fixture["gql_response"]
        ocm = get.return_value
        ocm.get_additional_routers.side_effect = lambda x: fixture["ocm_api"][x]

        integ.run(False)

        ocm_act = fixture["ocm_act"]

        router_create = ocm_act["create"]
        expected = [call(c, router_create[c]) for c in router_create]
        calls = ocm.create_additional_router.call_args_list
        self.assertEqual(calls, expected)

        router_delete = ocm_act["delete"]
        expected = []
        for c in router_delete:
            expected.append(call(c, router_delete[c]))
        calls = ocm.delete_additional_router.call_args_list
        self.assertEqual(calls, expected)

    # unit test
    @patch.object(queries, "get_app_interface_settings")
    @patch.object(OCMMap, "init_ocm_client_from_cluster")
    @patch.object(OCMMap, "get")
    def test_current_state(
        self,
        get: Mock,
        init_ocm_client_from_cluster: Mock,
        get_app_interface_settings: Mock,
    ) -> None:
        fixture = fxt.get_anymarkup("state.yml")

        ocm_api = fixture["ocm_api"]
        clusters: list[Mapping[str, Any]] = [{"name": c} for c in ocm_api]
        ocm = get.return_value
        ocm.get_additional_routers.side_effect = lambda x: fixture["ocm_api"][x]

        _, current_state = integ.fetch_current_state(clusters)
        expected = fixture["current_state"]
        self.assertEqual(current_state, expected)

    def test_desired_state(self) -> None:
        fixture = fxt.get_anymarkup("state.yml")

        gql_response = fixture["gql_response"]

        desired_state = integ.fetch_desired_state(gql_response)
        expected = fixture["desired_state"]
        self.assertEqual(desired_state, expected)

    def test_diffs(self) -> None:
        fixture = fxt.get_anymarkup("state.yml")

        current_state = fixture["current_state"]
        desired_state = fixture["desired_state"]

        diffs = integ.calculate_diff(current_state, desired_state)
        expected = fixture["diffs"]
        self.assertEqual(diffs, expected)

    @patch.object(OCMMap, "init_ocm_client_from_cluster")
    @patch.object(OCMMap, "get")
    def test_act(self, get: Mock, init_ocm_client_from_cluster: Mock) -> None:
        fixture = fxt.get_anymarkup("state.yml")
        ocm = get.return_value

        ocm_map = OCMMap(clusters=fixture["gql_response"])
        diffs = fixture["diffs"]
        integ.act(False, diffs, ocm_map)

        ocm_act = fixture["ocm_act"]

        router_create = ocm_act["create"]
        expected = [call(c, router_create[c]) for c in router_create]
        calls = ocm.create_additional_router.call_args_list
        self.assertEqual(calls, expected)

        router_delete = ocm_act["delete"]
        expected = []
        for c in router_delete:
            expected.append(call(c, router_delete[c]))
        calls = ocm.delete_additional_router.call_args_list
        self.assertEqual(calls, expected)
