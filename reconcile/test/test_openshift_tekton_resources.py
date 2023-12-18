# Setting ignore[misc] for setters on TstData:
# see https://github.com/python/mypy/issues/9160
# Made this a complete ignore because there are even more errors here that need
# to be addressed, but it was blocking other changes.
# type: ignore

from copy import deepcopy
from typing import Any
from unittest.mock import (
    create_autospec,
    patch,
)

import pytest

from reconcile import openshift_tekton_resources as otr
from reconcile.queries import PIPELINES_PROVIDERS_QUERY
from reconcile.utils import gql

from .fixtures import Fixtures

MODULE = "reconcile.openshift_tekton_resources"


class TstUnsupportedGqlQueryError(Exception):
    pass


class TstData:
    """Class to add data to tests in setUp. It will be used by mocks"""

    def __init__(self):
        self._providers = []
        self._saas_files = []

    @property
    def providers(self) -> list[dict[str, Any]]:
        return self._providers

    @property
    def saas_files(self) -> list[dict[str, Any]]:
        return self._saas_files

    @providers.setter
    def providers(self, providers: list[dict[str, Any]]) -> None:
        if not isinstance(providers, list):
            raise TypeError(f"Expecting list, have {type(providers)}")
        self._providers = providers

    @saas_files.setter
    def saas_files(self, saas_files: list[dict[str, Any]]) -> None:
        if not isinstance(saas_files, list):
            raise TypeError(f"Expecting list, have {type(saas_files)}")
        self._saas_files = saas_files


# This was originally written in unittest, hence the use of xunit-style
# setup/teardown methods instead of pytest fixtures.
class TestOpenshiftTektonResources:
    @staticmethod
    def _test_deploy_resources_in_task(
        desired_resources, task_name, deploy_resources
    ) -> None:
        """Helper method to test if deploy resources have been properly set"""
        for dr in desired_resources:
            if dr["name"] == task_name:
                task = dr["value"].body
                for step in task["spec"]["steps"]:
                    if step["name"] == otr.DEFAULT_DEPLOY_RESOURCES_STEP_NAME:
                        assert step["computeResources"] == deploy_resources
                break

    def mock_gql_get_resource(self, path: str) -> dict[str, str]:
        """Mock for GqlApi.get_resources using fixtures"""
        content = self.fxt.get(path)
        return {
            "path": path,
            "content": content,
            "sha256sum": "",
        }  # we do not need it for these tests

    def mock_gql_query(self, query: str) -> dict[str, Any]:
        """Mock for GqlApi.query using test_data set in setUp"""
        if query == otr.SAAS_FILES_QUERY:
            return {"saas_files": self.test_data.saas_files}
        if query == PIPELINES_PROVIDERS_QUERY:
            return {"pipelines_providers": self.test_data.providers}
        raise TstUnsupportedGqlQueryError("Unsupported query")

    def setup_method(self) -> None:
        self.test_data = TstData()

        self.fxt = Fixtures("openshift_tekton_resources")

        # Common fixtures
        self.saas1 = self.fxt.get_json("saas1.json")
        self.saas2 = self.fxt.get_json("saas2.json")
        self.saas2_wr = self.fxt.get_json("saas2-with-resources.json")
        self.provider1 = self.fxt.get_json("provider1.json")
        self.provider2_wr = self.fxt.get_json("provider2-with-resources.json")

        # Patcher for GqlApi methods
        self.gql_patcher = patch.object(gql, "get_api", autospec=True)
        self.gql = self.gql_patcher.start()
        gqlapi_mock = create_autospec(gql.GqlApi)
        self.gql.return_value = gqlapi_mock
        gqlapi_mock.query.side_effect = self.mock_gql_query
        gqlapi_mock.get_resource.side_effect = self.mock_gql_get_resource

    def teardown_method(self) -> None:
        """cleanup patches created in self.setUp"""
        self.gql_patcher.stop()

    def test_get_one_saas_file(self) -> None:
        self.test_data.saas_files = [self.saas1, self.saas2]
        saas_files = otr.fetch_saas_files(self.saas1["name"])
        assert saas_files == [self.saas1]

    def test_fetch_tkn_providers(self) -> None:
        self.test_data.saas_files = [self.saas1, self.saas2]
        self.test_data.providers = [self.provider1, self.provider2_wr]

        tkn_providers = otr.fetch_tkn_providers(None)
        keys_expected = set([self.provider1["name"], self.provider2_wr["name"]])
        assert tkn_providers.keys() == keys_expected

    def test_duplicate_providers(self) -> None:
        self.test_data.saas_files = [self.saas1]
        provider1_duplicate = deepcopy(self.provider1)
        self.test_data.providers = [self.provider1, provider1_duplicate]
        msg = r"There are duplicates in tekton providers names: provider1"
        with pytest.raises(otr.OpenshiftTektonResourcesBadConfigError, match=msg):
            otr.fetch_tkn_providers(None)

    def test_fetch_desired_resources(self) -> None:
        self.test_data.saas_files = [self.saas1, self.saas2, self.saas2_wr]
        self.test_data.providers = [self.provider1, self.provider2_wr]

        desired_resources = otr.fetch_desired_resources(otr.fetch_tkn_providers(None))

        # we have one task per namespace and a pipeline + task per saas file
        assert len(desired_resources) == 8

    def test_fetch_desired_resources_names(self) -> None:
        self.test_data.saas_files = [self.saas1]
        self.test_data.providers = [self.provider1]
        desired_resources = otr.fetch_desired_resources(otr.fetch_tkn_providers(None))

        expected_task_names = set([
            "o-push-gateway-openshift-saas-deploy-task-status-metric",
            "o-openshift-saas-deploy-saas1",
        ])
        expected_pipeline_name = "o-saas-deploy-saas1"

        task_names = set()
        for dr in desired_resources:
            body = dr["value"].body
            if body["kind"] == "Task":
                task_names.add(body["metadata"]["name"])
            else:
                pipeline_name = body["metadata"]["name"]

        assert task_names == expected_task_names
        assert pipeline_name == expected_pipeline_name

    def test_set_deploy_resources_default(self) -> None:
        self.test_data.saas_files = [self.saas1]
        self.test_data.providers = [self.provider1]
        desired_resources = otr.fetch_desired_resources(otr.fetch_tkn_providers(None))

        # we need to locate the onePerSaasFile task in the desired resources
        # we could be very strict and find the onePerSaasFile task in
        # self.provider1 or just use the actual structure of the fixtures
        task_name = otr.build_one_per_saas_file_tkn_task_name(
            template_name=self.provider1["taskTemplates"][0]["name"],
            saas_file_name=self.saas1["name"],
        )
        self._test_deploy_resources_in_task(
            desired_resources, task_name, otr.DEFAULT_DEPLOY_RESOURCES
        )

    def test_set_deploy_resources_from_provider(self) -> None:
        self.test_data.saas_files = [self.saas2]
        self.test_data.providers = [self.provider2_wr]
        desired_resources = otr.fetch_desired_resources(otr.fetch_tkn_providers(None))

        task_name = otr.build_one_per_saas_file_tkn_task_name(
            template_name=self.provider2_wr["taskTemplates"][0]["name"],
            saas_file_name=self.saas2["name"],
        )
        self._test_deploy_resources_in_task(
            desired_resources, task_name, self.provider2_wr["deployResources"]
        )

    def test_set_deploy_resources_from_saas_file(self) -> None:
        self.test_data.saas_files = [self.saas2_wr]
        self.test_data.providers = [self.provider2_wr]
        desired_resources = otr.fetch_desired_resources(otr.fetch_tkn_providers(None))

        task_name = otr.build_one_per_saas_file_tkn_task_name(
            template_name=self.provider2_wr["taskTemplates"][0]["name"],
            saas_file_name=self.saas2["name"],
        )
        self._test_deploy_resources_in_task(
            desired_resources, task_name, self.saas2_wr["deployResources"]
        )

    def test_task_templates_name_duplicates(self) -> None:
        self.provider4_wtd = self.fxt.get_json("provider4-with-task-duplicates.json")
        self.saas4 = self.fxt.get_json("saas4.json")
        self.test_data.saas_files = [self.saas4]
        self.test_data.providers = [self.provider4_wtd]

        msg = (
            r"There are duplicates in task templates names in tekton "
            r"provider provider4-with-task-duplicates"
        )
        with pytest.raises(otr.OpenshiftTektonResourcesBadConfigError, match=msg):
            otr.fetch_desired_resources(otr.fetch_tkn_providers(None))

    def test_task_templates_unknown_task(self) -> None:
        self.provider5_wut = self.fxt.get_json("provider5-with-unknown-task.json")
        self.saas5 = self.fxt.get_json("saas5.json")
        self.test_data.saas_files = [self.saas5]
        self.test_data.providers = [self.provider5_wut]

        msg = r"Unknown task this-is-an-unknown-task in pipeline template saas-deploy"
        with pytest.raises(otr.OpenshiftTektonResourcesBadConfigError, match=msg):
            otr.fetch_desired_resources(otr.fetch_tkn_providers(None))

    @patch(f"{MODULE}.DEFAULT_DEPLOY_RESOURCES_STEP_NAME", "unknown-step")
    def test_task_templates_unknown_deploy_resources_step(self) -> None:
        self.test_data.saas_files = [self.saas1]
        self.test_data.providers = [self.provider1]
        msg = (
            r"Cannot find a step named unknown-step to set resources in "
            r"task template openshift-saas-deploy"
        )
        with pytest.raises(otr.OpenshiftTektonResourcesBadConfigError, match=msg):
            otr.fetch_desired_resources(otr.fetch_tkn_providers(None))

    @patch(f"{MODULE}.RESOURCE_MAX_LENGTH", 10)
    def test_task_templates_resource_too_long(self) -> None:
        self.test_data.saas_files = [self.saas1]
        self.test_data.providers = [self.provider1]
        msg = (
            r"Resource name o-openshift-saas-deploy-saas1 is longer than 10 characters"
        )
        with pytest.raises(otr.OpenshiftTektonResourcesNameTooLongError, match=msg):
            otr.fetch_desired_resources(otr.fetch_tkn_providers(None))

    # This test describes a situation that should not take place in current app-interface since
    # pipeline names are limited to 15 characters. But just in case, the code protects us from
    # this situation to happen, hence the test.
    def test_pipeline_templates_resource_too_long(self) -> None:
        self.provider6_tlpn = self.fxt.get_json("provider6-too-long-pipeline-name.yaml")
        self.saas6_39cn = self.fxt.get_json("saas6-39-chars-name.yaml")
        self.test_data.saas_files = [self.saas6_39cn]
        self.test_data.providers = [self.provider6_tlpn]
        msg = (
            r"Pipeline name o-saas-deploy-too-long-name-this-is-a-saas-file-with-a-39-char-name "
            r"is longer than 56 characters"
        )
        with pytest.raises(otr.OpenshiftTektonResourcesNameTooLongError, match=msg):
            otr.fetch_desired_resources(otr.fetch_tkn_providers(None))
