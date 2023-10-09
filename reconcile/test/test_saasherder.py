from collections.abc import (
    Callable,
    Iterable,
    MutableMapping,
)
from typing import (
    Any,
    Optional,
)
from unittest import TestCase
from unittest.mock import (
    MagicMock,
    patch,
)

import pytest
import yaml
from github import (
    Github,
    GithubException,
)
from pydantic import BaseModel

from reconcile.gql_definitions.common.saas_files import (
    SaasFileV2,
    SaasResourceTemplateTargetImageV1,
    SaasResourceTemplateTargetPromotionV1,
    SaasResourceTemplateTargetV2_SaasSecretParametersV1,
    SaasResourceTemplateV2,
)
from reconcile.typed_queries.saas_files import SaasFile
from reconcile.utils.jjb_client import JJB
from reconcile.utils.openshift_resource import ResourceInventory
from reconcile.utils.saasherder import SaasHerder
from reconcile.utils.saasherder.interfaces import SaasFile as SaasFileInterface
from reconcile.utils.saasherder.models import (
    TriggerSpecMovingCommit,
    TriggerSpecUpstreamJob,
)
from reconcile.utils.secret_reader import SecretReaderBase

from .fixtures import Fixtures


class MockJJB:
    def __init__(self, data: dict[str, list[dict]]) -> None:
        self.jobs = data

    def get_all_jobs(self, job_types: Iterable[str]) -> dict[str, list[dict]]:
        return self.jobs

    @staticmethod
    def get_repo_url(job: dict[str, Any]) -> str:
        return JJB.get_repo_url(job)

    @staticmethod
    def get_ref(job: dict[str, Any]) -> str:
        return JJB.get_ref(job)


class MockSecretReader(SecretReaderBase):
    """
    Read secrets from a config file
    """

    def _read(
        self, path: str, field: str, format: Optional[str], version: Optional[int]
    ) -> str:
        return "secret"

    def _read_all(
        self, path: str, field: str, format: Optional[str], version: Optional[int]
    ) -> dict[str, str]:
        return {"param": "secret"}


@pytest.fixture()
def inject_gql_class_factory(
    request: pytest.FixtureRequest,
    gql_class_factory: Callable[..., SaasFileV2],
) -> None:
    def _gql_class_factory(
        self: Any,
        klass: type[BaseModel],
        data: Optional[MutableMapping[str, Any]] = None,
    ) -> BaseModel:
        return gql_class_factory(klass, data)

    request.cls.gql_class_factory = _gql_class_factory


@pytest.mark.usefixtures("inject_gql_class_factory")
class TestSaasFileValid(TestCase):
    def setUp(self) -> None:
        self.saas_file = self.gql_class_factory(  # type: ignore[attr-defined] # it's set in the fixture
            SaasFileV2, Fixtures("saasherder").get_anymarkup("saas.gql.yml")
        )
        jjb_mock_data = {
            "ci": [
                {
                    "name": "job",
                    "properties": [
                        {
                            "github": {
                                "url": "https://github.com/app-sre/test-saas-deployments"
                            }
                        }
                    ],
                    "scm": [{"git": {"branches": ["main"]}}],
                },
                {
                    "name": "job",
                    "properties": [
                        {
                            "github": {
                                "url": "https://github.com/app-sre/test-saas-deployments"
                            }
                        }
                    ],
                    "scm": [{"git": {"branches": ["master"]}}],
                },
            ]
        }
        self.jjb = MockJJB(jjb_mock_data)

    def test_check_saas_file_env_combo_unique(self) -> None:
        saasherder = SaasHerder(
            [self.saas_file],
            secret_reader=MockSecretReader(),
            thread_pool_size=1,
            integration="",
            integration_version="",
            hash_length=7,
            repo_url="https://repo-url.com",
            validate=True,
        )
        self.assertTrue(saasherder.valid)

    def test_check_saas_file_env_combo_not_unique(self) -> None:
        self.saas_file.name = "long-name-which-is-too-long-to-produce-unique-combo"
        saasherder = SaasHerder(
            [self.saas_file],
            secret_reader=MockSecretReader(),
            thread_pool_size=1,
            integration="",
            integration_version="",
            hash_length=7,
            repo_url="https://repo-url.com",
            validate=True,
        )

        self.assertFalse(saasherder.valid)

    def test_saas_file_auto_promotion_used_with_commit_sha(self) -> None:
        self.saas_file.resource_templates[0].targets[
            1
        ].ref = "1234567890123456789012345678901234567890"
        self.saas_file.resource_templates[0].targets[
            1
        ].promotion = SaasResourceTemplateTargetPromotionV1(
            auto=True, publish=None, subscribe=None, promotion_data=None
        )
        saasherder = SaasHerder(
            [self.saas_file],
            secret_reader=MockSecretReader(),
            thread_pool_size=1,
            integration="",
            integration_version="",
            hash_length=7,
            repo_url="https://repo-url.com",
            validate=True,
        )

        self.assertTrue(saasherder.valid)

    def test_saas_file_auto_promotion_not_used_with_commit_sha(self) -> None:
        self.saas_file.resource_templates[0].targets[1].ref = "main"
        self.saas_file.resource_templates[0].targets[
            1
        ].promotion = SaasResourceTemplateTargetPromotionV1(
            auto=True, publish=None, subscribe=None, promotion_data=None
        )
        saasherder = SaasHerder(
            [self.saas_file],
            secret_reader=MockSecretReader(),
            thread_pool_size=1,
            integration="",
            integration_version="",
            hash_length=7,
            repo_url="https://repo-url.com",
            validate=True,
        )

        self.assertFalse(saasherder.valid)

    def test_check_saas_file_upstream_not_used_with_commit_sha(self) -> None:
        saasherder = SaasHerder(
            [self.saas_file],
            secret_reader=MockSecretReader(),
            thread_pool_size=1,
            integration="",
            integration_version="",
            hash_length=7,
            repo_url="https://repo-url.com",
            validate=True,
        )

        self.assertTrue(saasherder.valid)

    def test_check_saas_file_upstream_used_with_commit_sha(self) -> None:
        self.saas_file.resource_templates[0].targets[
            0
        ].ref = "2637b6c41bda7731b1bcaaf18b4a50d7c5e63e30"
        saasherder = SaasHerder(
            [self.saas_file],
            secret_reader=MockSecretReader(),
            thread_pool_size=1,
            integration="",
            integration_version="",
            hash_length=7,
            repo_url="https://repo-url.com",
            validate=True,
        )

        self.assertFalse(saasherder.valid)

    def test_dangling_target_config_hash(self) -> None:
        self.saas_file.resource_templates[0].targets[1].promotion.promotion_data[
            0
        ].channel = "does-not-exist"
        saasherder = SaasHerder(
            [self.saas_file],
            secret_reader=MockSecretReader(),
            thread_pool_size=1,
            integration="",
            integration_version="",
            hash_length=7,
            repo_url="https://repo-url.com",
            validate=True,
        )

        self.assertFalse(saasherder.valid)

    def test_check_saas_file_upstream_used_with_image(self) -> None:
        self.saas_file.resource_templates[0].targets[
            0
        ].image = SaasResourceTemplateTargetImageV1(
            **{"name": "image", "org": {"name": "org", "instance": {"url": "url"}}}
        )
        saasherder = SaasHerder(
            [self.saas_file],
            secret_reader=MockSecretReader(),
            thread_pool_size=1,
            integration="",
            integration_version="",
            hash_length=7,
            repo_url="https://repo-url.com",
            validate=True,
        )

        self.assertFalse(saasherder.valid)

    def test_check_saas_file_image_used_with_commit_sha(self) -> None:
        self.saas_file.resource_templates[0].targets[
            0
        ].ref = "2637b6c41bda7731b1bcaaf18b4a50d7c5e63e30"
        self.saas_file.resource_templates[0].targets[
            0
        ].image = SaasResourceTemplateTargetImageV1(
            **{"name": "image", "org": {"name": "org", "instance": {"url": "url"}}}
        )
        saasherder = SaasHerder(
            [self.saas_file],
            secret_reader=MockSecretReader(),
            thread_pool_size=1,
            integration="",
            integration_version="",
            hash_length=7,
            repo_url="https://repo-url.com",
            validate=True,
        )

        self.assertFalse(saasherder.valid)

    def test_validate_image_tag_not_equals_ref_valid(self) -> None:
        self.saas_file.resource_templates[0].targets[0].parameters = {
            "IMAGE_TAG": "2637b6c"
        }
        saasherder = SaasHerder(
            [self.saas_file],
            secret_reader=MockSecretReader(),
            thread_pool_size=1,
            integration="",
            integration_version="",
            hash_length=7,
            repo_url="https://repo-url.com",
            validate=True,
        )

        self.assertTrue(saasherder.valid)

    def test_validate_image_tag_not_equals_ref_invalid(self) -> None:
        self.saas_file.resource_templates[0].targets[
            0
        ].ref = "2637b6c41bda7731b1bcaaf18b4a50d7c5e63e30"
        self.saas_file.resource_templates[0].targets[0].parameters = {
            "IMAGE_TAG": "2637b6c"
        }
        saasherder = SaasHerder(
            [self.saas_file],
            secret_reader=MockSecretReader(),
            thread_pool_size=1,
            integration="",
            integration_version="",
            hash_length=7,
            repo_url="https://repo-url.com",
            validate=True,
        )

        self.assertFalse(saasherder.valid)

    def test_validate_upstream_jobs_valid(self) -> None:
        saasherder = SaasHerder(
            [self.saas_file],
            secret_reader=MockSecretReader(),
            thread_pool_size=1,
            integration="",
            integration_version="",
            hash_length=7,
            repo_url="https://repo-url.com",
            validate=True,
        )
        saasherder.validate_upstream_jobs(self.jjb)  # type: ignore
        self.assertTrue(saasherder.valid)

    def test_validate_upstream_jobs_invalid(self) -> None:
        saasherder = SaasHerder(
            [self.saas_file],
            secret_reader=MockSecretReader(),
            thread_pool_size=1,
            integration="",
            integration_version="",
            hash_length=7,
            repo_url="https://repo-url.com",
            validate=True,
        )
        jjb = MockJJB({"ci": []})
        saasherder.validate_upstream_jobs(jjb)  # type: ignore
        self.assertFalse(saasherder.valid)

    def test_check_saas_file_promotion_same_source(self) -> None:
        raw_rts = [
            {
                "name": "rt_publisher",
                "url": "repo_publisher",
                "path": "path",
                "targets": [
                    {
                        "namespace": {
                            "name": "ns",
                            "app": {"name": "app"},
                            "environment": {
                                "name": "env1",
                            },
                            "cluster": {
                                "name": "appsres03ue1",
                                "serverUrl": "https://url",
                                "internal": True,
                            },
                        },
                        "parameters": "{}",
                        "ref": "0000000000000",
                        "promotion": {
                            "publish": ["channel-1"],
                        },
                    }
                ],
            },
            {
                "name": "rt_subscriber",
                "url": "this-repo-will-not-match-the-publisher",
                "path": "path",
                "targets": [
                    {
                        "namespace": {
                            "name": "ns2",
                            "app": {"name": "app"},
                            "environment": {
                                "name": "env1",
                            },
                            "cluster": {
                                "name": "appsres03ue1",
                                "serverUrl": "https://url",
                                "internal": True,
                            },
                        },
                        "parameters": "{}",
                        "ref": "0000000000000",
                        "promotion": {
                            "auto": "True",
                            "subscribe": ["channel-1"],
                        },
                    }
                ],
            },
        ]
        rts = [
            self.gql_class_factory(  # type: ignore[attr-defined] # it's set in the fixture
                SaasResourceTemplateV2, rt
            )
            for rt in raw_rts
        ]
        self.saas_file.resource_templates = rts
        saasherder = SaasHerder(
            [self.saas_file],
            secret_reader=MockSecretReader(),
            thread_pool_size=1,
            integration="",
            integration_version="",
            hash_length=7,
            repo_url="https://repo-url.com",
            validate=True,
        )
        self.assertFalse(saasherder.valid)


@pytest.mark.usefixtures("inject_gql_class_factory")
class TestGetMovingCommitsDiffSaasFile(TestCase):
    def setUp(self) -> None:
        self.saas_file = self.gql_class_factory(  # type: ignore[attr-defined] # it's set in the fixture
            SaasFileV2, Fixtures("saasherder").get_anymarkup("saas.gql.yml")
        )

        self.initiate_gh_patcher = patch.object(
            SaasHerder, "_initiate_github", autospec=True
        )
        self.get_commit_sha_patcher = patch.object(
            SaasHerder, "_get_commit_sha", autospec=True
        )
        self.initiate_gh = self.initiate_gh_patcher.start()
        self.get_commit_sha = self.get_commit_sha_patcher.start()
        self.maxDiff = None

    def tearDown(self) -> None:
        for p in (
            self.initiate_gh_patcher,
            self.get_commit_sha_patcher,
        ):
            p.stop()

    def test_get_moving_commits_diff_saas_file_all_fine(self) -> None:
        saasherder = SaasHerder(
            [self.saas_file],
            secret_reader=MockSecretReader(),
            thread_pool_size=1,
            integration="",
            integration_version="",
            hash_length=7,
            repo_url="https://repo-url.com",
        )
        saasherder.state = MagicMock()
        saasherder.state.get.return_value = "asha"
        self.get_commit_sha.side_effect = ("abcd4242",)
        # 2nd target is the one that will be promoted
        expected = [
            TriggerSpecMovingCommit(
                saas_file_name=self.saas_file.name,
                env_name="App-SRE",
                timeout=None,
                pipelines_provider=self.saas_file.pipelines_provider,
                resource_template_name="test-saas-deployments",
                cluster_name="appsres03ue1",
                namespace_name="test-ns-subscriber",
                state_content="abcd4242",
                ref="1234567890123456789012345678901234567890",
                reason=None,
            )
        ]

        self.assertEqual(
            saasherder.get_moving_commits_diff_saas_file(self.saas_file, True),
            expected,
        )

    def test_get_moving_commits_diff_saas_file_all_fine_include_trigger_trace(
        self,
    ) -> None:
        saasherder = SaasHerder(
            [self.saas_file],
            secret_reader=MockSecretReader(),
            thread_pool_size=1,
            integration="",
            integration_version="",
            hash_length=7,
            repo_url="https://repo-url.com",
            include_trigger_trace=True,
        )

        saasherder.state = MagicMock()
        saasherder.state.get.return_value = "asha"
        self.get_commit_sha.side_effect = ("abcd4242", "4242efg")
        expected = [
            TriggerSpecMovingCommit(
                saas_file_name=self.saas_file.name,
                env_name="App-SRE",
                timeout=None,
                pipelines_provider=self.saas_file.pipelines_provider,
                resource_template_name="test-saas-deployments",
                cluster_name="appsres03ue1",
                namespace_name="test-ns-subscriber",
                state_content="abcd4242",
                ref="1234567890123456789012345678901234567890",
                reason="https://github.com/app-sre/test-saas-deployments/commit/abcd4242",
            ),
        ]

        self.assertEqual(
            saasherder.get_moving_commits_diff_saas_file(self.saas_file, True),
            expected,
        )

    def test_get_moving_commits_diff_saas_file_bad_sha1(self) -> None:
        saasherder = SaasHerder(
            [self.saas_file],
            secret_reader=MockSecretReader(),
            thread_pool_size=1,
            integration="",
            integration_version="",
            hash_length=7,
            repo_url="https://repo-url.com",
        )
        saasherder.state = MagicMock()
        saasherder.state.get.return_value = "asha"
        self.get_commit_sha.side_effect = GithubException(
            401, "somedata", {"aheader": "avalue"}
        )
        # At least we don't crash!
        self.assertEqual(
            saasherder.get_moving_commits_diff_saas_file(self.saas_file, True), []
        )


@pytest.mark.usefixtures("inject_gql_class_factory")
class TestGetUpstreamJobsDiffSaasFile(TestCase):
    def setUp(self) -> None:
        self.saas_file = self.gql_class_factory(  # type: ignore[attr-defined] # it's set in the fixture
            SaasFileV2, Fixtures("saasherder").get_anymarkup("saas.gql.yml")
        )
        self.maxDiff = None

    def test_get_upstream_jobs_diff_saas_file_all_fine(self) -> None:
        state_content = {"number": 2, "result": "SUCCESS", "commit_sha": "abcd4242"}
        current_state = {"ci": {"job": [state_content]}}
        saasherder = SaasHerder(
            [self.saas_file],
            secret_reader=MockSecretReader(),
            thread_pool_size=1,
            integration="",
            integration_version="",
            hash_length=7,
            repo_url="https://repo-url.com",
        )
        saasherder.state = MagicMock()
        saasherder.state.get.return_value = {
            "number": 1,
            "result": "SUCCESS",
            "commit_sha": "4242efg",
        }
        expected = [
            TriggerSpecUpstreamJob(
                saas_file_name=self.saas_file.name,
                env_name="App-SRE-stage",
                timeout=None,
                pipelines_provider=self.saas_file.pipelines_provider,
                resource_template_name="test-saas-deployments",
                cluster_name="appsres03ue1",
                namespace_name="test-ns-publisher",
                instance_name="ci",
                job_name="job",
                state_content=state_content,
                reason=None,
            )
        ]

        self.assertEqual(
            saasherder.get_upstream_jobs_diff_saas_file(
                self.saas_file, True, current_state
            ),
            expected,
        )

    def test_get_upstream_jobs_diff_saas_file_all_fine_include_trigger_trace(
        self,
    ) -> None:
        state_content = {"number": 2, "result": "SUCCESS", "commit_sha": "abcd4242"}
        current_state = {"ci": {"job": [state_content]}}
        saasherder = SaasHerder(
            [self.saas_file],
            secret_reader=MockSecretReader(),
            thread_pool_size=1,
            integration="",
            integration_version="",
            hash_length=7,
            repo_url="https://repo-url.com",
            include_trigger_trace=True,
        )
        saasherder.state = MagicMock()
        saasherder.state.get.return_value = {
            "number": 1,
            "result": "SUCCESS",
            "commit_sha": "4242efg",
        }
        expected = [
            TriggerSpecUpstreamJob(
                saas_file_name=self.saas_file.name,
                env_name="App-SRE-stage",
                timeout=None,
                pipelines_provider=self.saas_file.pipelines_provider,
                resource_template_name="test-saas-deployments",
                cluster_name="appsres03ue1",
                namespace_name="test-ns-publisher",
                instance_name="ci",
                job_name="job",
                state_content=state_content,
                reason="https://github.com/app-sre/test-saas-deployments/commit/abcd4242 via https://jenkins.com/job/job/2",
            )
        ]

        self.assertEqual(
            saasherder.get_upstream_jobs_diff_saas_file(
                self.saas_file, True, current_state
            ),
            expected,
        )

    def test_get_archive_info(self) -> None:
        trigger_reason = "https://gitlab.com/app-sre/test-saas-deployments/commit/abcd4242 via https://jenkins.com/job/job/2"
        saasherder = SaasHerder(
            [self.saas_file],
            secret_reader=MockSecretReader(),
            thread_pool_size=1,
            integration="",
            integration_version="",
            hash_length=7,
            repo_url="https://repo-url.com",
            include_trigger_trace=True,
        )
        file_name = "app-sre-test-saas-deployments-abcd4242.tar.gz"
        archive_url = f"https://gitlab.com/app-sre/test-saas-deployments/-/archive/abcd4242/{file_name}"
        self.assertEqual(
            saasherder.get_archive_info(self.saas_file, trigger_reason),
            (file_name, archive_url),
        )


@pytest.mark.usefixtures("inject_gql_class_factory")
class TestPopulateDesiredState(TestCase):
    def setUp(self) -> None:
        self.fxts = Fixtures("saasherder_populate_desired")
        raw_saas_file = self.fxts.get_anymarkup("saas_remote_openshift_template.yaml")
        del raw_saas_file["_placeholders"]
        saas_file = self.gql_class_factory(  # type: ignore[attr-defined] # it's set in the fixture
            SaasFileV2, raw_saas_file
        )
        self.saasherder = SaasHerder(
            [saas_file],
            secret_reader=MockSecretReader(),
            thread_pool_size=1,
            integration="",
            integration_version="",
            hash_length=7,
            repo_url="https://repo-url.com",
        )

        # Mock GitHub interactions.
        self.initiate_gh_patcher = patch.object(
            SaasHerder,
            "_initiate_github",
            autospec=True,
            return_value=None,
        )
        self.get_file_contents_patcher = patch.object(
            SaasHerder,
            "_get_file_contents",
            wraps=self.fake_get_file_contents,
        )
        self.initiate_gh_patcher.start()
        self.get_file_contents_patcher.start()

        # Mock image checking.
        self.get_check_images_patcher = patch.object(
            SaasHerder,
            "_check_images",
            autospec=True,
            return_value=None,
        )
        self.get_check_images_patcher.start()

    def fake_get_file_contents(
        self, url: str, path: str, ref: str, github: Github
    ) -> tuple[Any, str, str]:
        self.assertEqual("https://github.com/rhobs/configuration", url)

        content = self.fxts.get(ref + (path.replace("/", "_")))
        return yaml.safe_load(content), "yolo", ref

    def tearDown(self) -> None:
        for p in (
            self.initiate_gh_patcher,
            self.get_file_contents_patcher,
            self.get_check_images_patcher,
        ):
            p.stop()

    def test_populate_desired_state_cases(self) -> None:
        ri = ResourceInventory()
        for resource_type in (
            "Deployment",
            "Service",
            "ConfigMap",
        ):
            ri.initialize_resource_type("stage-1", "yolo-stage", resource_type)
            ri.initialize_resource_type("prod-1", "yolo", resource_type)
        self.saasherder.populate_desired_state(ri)

        cnt = 0
        for cluster, namespace, resource_type, data in ri:
            for _, d_item in data["desired"].items():
                expected = yaml.safe_load(
                    self.fxts.get(
                        f"expected_{cluster}_{namespace}_{resource_type}.json",
                    )
                )
                self.assertEqual(expected, d_item.body)
                cnt += 1

        self.assertEqual(5, cnt, "expected 5 resources, found less")
        self.assertEqual(self.saasherder.promotions, [None, None, None, None])


@pytest.mark.usefixtures("inject_gql_class_factory")
class TestCollectRepoUrls(TestCase):
    def setUp(self) -> None:
        self.saas_file = self.gql_class_factory(  # type: ignore[attr-defined] # it's set in the fixture
            SaasFileV2, Fixtures("saasherder").get_anymarkup("saas.gql.yml")
        )

    def test_collect_repo_urls(self) -> None:
        repo_url = "https://github.com/app-sre/test-saas-deployments"
        saasherder = SaasHerder(
            [self.saas_file],
            secret_reader=MockSecretReader(),
            thread_pool_size=1,
            integration="",
            integration_version="",
            hash_length=7,
            repo_url="https://repo-url.com",
        )
        self.assertEqual({repo_url}, saasherder.repo_urls)


@pytest.mark.usefixtures("inject_gql_class_factory")
class TestGetSaasFileAttribute(TestCase):
    def setUp(self) -> None:
        self.saas_file = self.gql_class_factory(  # type: ignore[attr-defined] # it's set in the fixture
            SaasFileV2, Fixtures("saasherder").get_anymarkup("saas.gql.yml")
        )

    def test_no_such_attribute(self) -> None:
        saasherder = SaasHerder(
            [self.saas_file],
            secret_reader=MockSecretReader(),
            thread_pool_size=1,
            integration="",
            integration_version="",
            hash_length=7,
            repo_url="https://repo-url.com",
        )
        att = saasherder._get_saas_file_feature_enabled("no_such_attribute")
        self.assertEqual(att, None)

    def test_attribute_none(self) -> None:
        saasherder = SaasHerder(
            [self.saas_file],
            secret_reader=MockSecretReader(),
            thread_pool_size=1,
            integration="",
            integration_version="",
            hash_length=7,
            repo_url="https://repo-url.com",
        )
        att = saasherder._get_saas_file_feature_enabled("takeover")
        self.assertEqual(att, None)

    def test_attribute_not_none(self) -> None:
        saasherder = SaasHerder(
            [self.saas_file],
            secret_reader=MockSecretReader(),
            thread_pool_size=1,
            integration="",
            integration_version="",
            hash_length=7,
            repo_url="https://repo-url.com",
        )
        att = saasherder._get_saas_file_feature_enabled("publish_job_logs")
        self.assertEqual(att, True)

    def test_attribute_none_with_default(self) -> None:
        saasherder = SaasHerder(
            [self.saas_file],
            secret_reader=MockSecretReader(),
            thread_pool_size=1,
            integration="",
            integration_version="",
            hash_length=7,
            repo_url="https://repo-url.com",
        )
        att = saasherder._get_saas_file_feature_enabled("no_such_att", default=True)
        self.assertEqual(att, True)

    def test_attribute_not_none_with_default(self) -> None:
        saasherder = SaasHerder(
            [self.saas_file],
            secret_reader=MockSecretReader(),
            thread_pool_size=1,
            integration="",
            integration_version="",
            hash_length=7,
            repo_url="https://repo-url.com",
        )
        att = saasherder._get_saas_file_feature_enabled(
            "publish_job_logs", default=False
        )
        self.assertEqual(att, True)

    def test_attribute_multiple_saas_files_return_false(self) -> None:
        saasherder = SaasHerder(
            [self.saas_file, self.saas_file],
            secret_reader=MockSecretReader(),
            thread_pool_size=1,
            integration="",
            integration_version="",
            hash_length=7,
            repo_url="https://repo-url.com",
        )
        self.assertFalse(saasherder._get_saas_file_feature_enabled("publish_job_logs"))

    def test_attribute_multiple_saas_files_with_default_return_false(self) -> None:
        saasherder = SaasHerder(
            [self.saas_file, self.saas_file],
            secret_reader=MockSecretReader(),
            thread_pool_size=1,
            integration="",
            integration_version="",
            hash_length=7,
            repo_url="https://repo-url.com",
        )
        att = saasherder._get_saas_file_feature_enabled("attrib", default=True)
        self.assertFalse(att)


@pytest.mark.usefixtures("inject_gql_class_factory")
class TestConfigHashPromotionsValidation(TestCase):
    """TestCase to test SaasHerder promotions validation. SaasHerder is
    initialized with ResourceInventory population. Like is done in
    openshift-saas-deploy"""

    cluster: str
    namespace: str
    fxt: Any
    template: Any

    @classmethod
    def setUpClass(cls) -> None:
        cls.fxt = Fixtures("saasherder")
        cls.cluster = "test-cluster"
        cls.template = cls.fxt.get_anymarkup("template_1.yml")

    def setUp(self) -> None:
        self.saas_file = self.gql_class_factory(  # type: ignore[attr-defined] # it's set in the fixture
            SaasFile, Fixtures("saasherder").get_anymarkup("saas.gql.yml")
        )
        self.state_patcher = patch("reconcile.utils.state.State", autospec=True)
        self.state_mock = self.state_patcher.start().return_value

        self.ig_patcher = patch.object(SaasHerder, "_initiate_github", autospec=True)
        self.ig_patcher.start()

        self.image_auth_patcher = patch.object(SaasHerder, "_initiate_image_auth")
        self.image_auth_patcher.start()

        self.gfc_patcher = patch.object(SaasHerder, "_get_file_contents", autospec=True)
        gfc_mock = self.gfc_patcher.start()
        gfc_mock.return_value = (self.template, "url", "ahash")

        self.deploy_current_state_fxt = self.fxt.get_anymarkup("saas_deploy.state.json")

        self.post_deploy_current_state_fxt = self.fxt.get_anymarkup(
            "saas_post_deploy.state.json"
        )

        self.saasherder = SaasHerder(
            [self.saas_file],
            secret_reader=MockSecretReader(),
            thread_pool_size=1,
            state=self.state_mock,
            integration="",
            integration_version="",
            hash_length=24,
            repo_url="https://repo-url.com",
            all_saas_files=[self.saas_file],
        )

        # IMPORTANT: Populating desired state modify self.saas_files within
        # saasherder object.
        self.ri = ResourceInventory()
        for ns in ["test-ns-publisher", "test-ns-subscriber"]:
            for kind in ["Service", "Deployment"]:
                self.ri.initialize_resource_type(self.cluster, ns, kind)

        self.saasherder.populate_desired_state(self.ri)
        if self.ri.has_error_registered():
            raise Exception("Errors registered in Resourceinventory")

    def tearDown(self) -> None:
        self.state_patcher.stop()
        self.ig_patcher.stop()
        self.gfc_patcher.stop()

    def test_promotion_state_config_hash_match_validates(self) -> None:
        """A promotion is valid if the parent target config_hash set in
        the state is equal to the one set in the subscriber target
        promotion data. This is the happy path.
        """
        publisher_state = {
            "success": True,
            "saas_file": self.saas_file.name,
            "target_config_hash": "ed2af38cf21f268c",
        }
        self.state_mock.get.return_value = publisher_state
        result = self.saasherder.validate_promotions()
        self.assertTrue(result)

    def test_promotion_state_config_hash_not_match_no_validates(self) -> None:
        """Promotion is not valid if the parent target config hash set in
        the state does not match with the one set in the subscriber target
        promotion_data. This could happen if the parent target has run again
        with the same ref before before the subscriber target promotion MR is
        merged.
        """
        publisher_state = {
            "success": True,
            "saas_file": self.saas_file.name,
            "target_config_hash": "will_not_match",
        }
        self.state_mock.get.return_value = publisher_state
        result = self.saasherder.validate_promotions()
        self.assertFalse(result)

    def test_promotion_without_state_config_hash_validates(self) -> None:
        """Existent states won't have promotion data. If there is an ongoing
        promotion, this ensures it will happen.
        """
        publisher_state = {
            "success": True,
        }
        self.state_mock.get.return_value = publisher_state
        result = self.saasherder.validate_promotions()
        self.assertTrue(result)

    def test_promotion_without_promotion_data_validates(self) -> None:
        """A manual promotion might be required, subsribed targets without
        promotion_data should validate if the parent target job has succed
        with the same ref.
        """
        publisher_state = {
            "success": True,
            "saas_file": self.saas_file.name,
            "target_config_hash": "whatever",
        }

        self.assertEqual(len(self.saasherder.promotions), 2)
        self.assertIsNotNone(self.saasherder.promotions[1])
        # Remove promotion_data on the promoted target
        self.saasherder.promotions[1].promotion_data = None  # type: ignore

        self.state_mock.get.return_value = publisher_state
        result = self.saasherder.validate_promotions()
        self.assertTrue(result)


@pytest.mark.usefixtures("inject_gql_class_factory")
class TestConfigHashTrigger(TestCase):
    """TestCase to test Openshift SAAS deploy configs trigger. SaasHerder is
    initialized WITHOUT ResourceInventory population. Like is done in the
    config changes trigger"""

    cluster: str
    namespace: str
    fxt: Any
    template: Any

    @classmethod
    def setUpClass(cls) -> None:
        cls.fxt = Fixtures("saasherder")
        cls.cluster = "test-cluster"

    def setUp(self) -> None:
        self.saas_file = self.gql_class_factory(  # type: ignore[attr-defined] # it's set in the fixture
            SaasFile, Fixtures("saasherder").get_anymarkup("saas.gql.yml")
        )
        self.state_patcher = patch("reconcile.utils.state.State", autospec=True)
        self.state_mock = self.state_patcher.start().return_value

        self.deploy_current_state_fxt = self.fxt.get_anymarkup("saas_deploy.state.json")

        self.post_deploy_current_state_fxt = self.fxt.get_anymarkup(
            "saas_post_deploy.state.json"
        )

        self.state_mock.get.side_effect = [
            self.deploy_current_state_fxt,
            self.post_deploy_current_state_fxt,
        ]

        self.saasherder = SaasHerder(
            [self.saas_file],
            secret_reader=MockSecretReader(),
            thread_pool_size=1,
            state=self.state_mock,
            integration="",
            integration_version="",
            hash_length=24,
            repo_url="https://repo-url.com",
            all_saas_files=[self.saas_file],
        )

    def tearDown(self) -> None:
        self.state_patcher.stop()

    def test_same_configs_do_not_trigger(self) -> None:
        """Ensures that if the same config is found, no job is triggered
        current Config is fetched from the state
        """
        trigger_specs = self.saasherder.get_configs_diff_saas_file(self.saas_file)
        self.assertListEqual(trigger_specs, [])

    def test_config_hash_change_do_trigger(self) -> None:
        """Ensures a new job is triggered if the parent config hash changes"""
        self.saasherder.saas_files[0].resource_templates[0].targets[  # type: ignore
            1
        ].promotion.promotion_data[0].data[0].target_config_hash = "Changed"
        trigger_specs = self.saasherder.get_configs_diff_saas_file(self.saas_file)
        self.assertEqual(len(trigger_specs), 1)

    def test_non_existent_config_triggers(self) -> None:
        self.state_mock.get.side_effect = [self.deploy_current_state_fxt, None]
        trigger_specs = self.saasherder.get_configs_diff_saas_file(self.saas_file)
        self.assertEqual(len(trigger_specs), 1)


class TestRemoveNoneAttributes(TestCase):
    def testSimpleDict(self) -> None:
        input = {"a": 1, "b": {}, "d": None, "e": {"aa": "aa", "bb": None}}
        expected = {"a": 1, "b": {}, "e": {"aa": "aa"}}
        res = SaasHerder.remove_none_values(input)
        self.assertEqual(res, expected)

    def testNoneValue(self) -> None:
        input = None
        expected: dict[Any, Any] = {}
        res = SaasHerder.remove_none_values(input)
        self.assertEqual(res, expected)


def test_render_templated_parameters(
    gql_class_factory: Callable[..., SaasFileInterface]
) -> None:
    saas_file = gql_class_factory(
        SaasFileV2,
        Fixtures("saasherder").get_anymarkup("saas-templated-params.gql.yml"),
    )
    SaasHerder.resolve_templated_parameters([saas_file])
    assert saas_file.resource_templates[0].targets[0].parameters == {
        "no-template": "v1",
        "ignore-go-template": "{{ .GO_PARAM }}-go",
        "template-param-1": "test-namespace-ns",
        "template-param-2": "appsres03ue1-cluster",
    }
    assert saas_file.resource_templates[0].targets[0].secret_parameters == [
        SaasResourceTemplateTargetV2_SaasSecretParametersV1(
            name="no-template",
            secret=dict(
                path="path/to/secret",
                field="secret_key",
                version=1,
                format=None,
            ),
        ),
        SaasResourceTemplateTargetV2_SaasSecretParametersV1(
            name="ignore-go-template",
            secret=dict(
                path="path/{{ .GO_PARAM }}/secret",
                field="{{ .GO_PARAM }}-secret_key",
                version=1,
                format=None,
            ),
        ),
        SaasResourceTemplateTargetV2_SaasSecretParametersV1(
            name="template-param-1",
            secret=dict(
                path="path/appsres03ue1/test-namespace/secret",
                field="secret_key",
                version=1,
                format=None,
            ),
        ),
        SaasResourceTemplateTargetV2_SaasSecretParametersV1(
            name="template-param-2",
            secret=dict(
                path="path/appsres03ue1/test-namespace/secret",
                field="App-SRE-stage-secret_key",
                version=1,
                format=None,
            ),
        ),
    ]


def test_render_templated_parameters_in_init(
    gql_class_factory: Callable[..., SaasFile]
) -> None:
    saas_file = gql_class_factory(
        SaasFileV2,
        Fixtures("saasherder").get_anymarkup("saas-templated-params.gql.yml"),
    )
    SaasHerder(
        [saas_file],
        secret_reader=MockSecretReader(),
        thread_pool_size=1,
        integration="",
        integration_version="",
        hash_length=24,
        repo_url="https://repo-url.com",
    )
    assert saas_file.resource_templates[0].targets[0].parameters == {
        "no-template": "v1",
        "ignore-go-template": "{{ .GO_PARAM }}-go",
        "template-param-1": "test-namespace-ns",
        "template-param-2": "appsres03ue1-cluster",
    }
    assert saas_file.resource_templates[0].targets[0].secret_parameters == [
        SaasResourceTemplateTargetV2_SaasSecretParametersV1(
            name="no-template",
            secret=dict(
                path="path/to/secret",
                field="secret_key",
                version=1,
                format=None,
            ),
        ),
        SaasResourceTemplateTargetV2_SaasSecretParametersV1(
            name="ignore-go-template",
            secret=dict(
                path="path/{{ .GO_PARAM }}/secret",
                field="{{ .GO_PARAM }}-secret_key",
                version=1,
                format=None,
            ),
        ),
        SaasResourceTemplateTargetV2_SaasSecretParametersV1(
            name="template-param-1",
            secret=dict(
                path="path/appsres03ue1/test-namespace/secret",
                field="secret_key",
                version=1,
                format=None,
            ),
        ),
        SaasResourceTemplateTargetV2_SaasSecretParametersV1(
            name="template-param-2",
            secret=dict(
                path="path/appsres03ue1/test-namespace/secret",
                field="App-SRE-stage-secret_key",
                version=1,
                format=None,
            ),
        ),
    ]
