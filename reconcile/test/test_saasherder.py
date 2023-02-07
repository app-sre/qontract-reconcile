from typing import Any
from unittest import TestCase
from unittest.mock import (
    MagicMock,
    patch,
)

import yaml
from github import GithubException

from reconcile.utils.jjb_client import JJB
from reconcile.utils.openshift_resource import ResourceInventory
from reconcile.utils.saasherder import (
    TARGET_CONFIG_HASH,
    SaasHerder,
    TriggerSpecConfig,
    TriggerSpecMovingCommit,
)

from .fixtures import Fixtures


class MockJJB:
    def __init__(self, data):
        self.jobs = data

    def get_all_jobs(self, job_types):
        return self.jobs

    @staticmethod
    def get_repo_url(job):
        return JJB.get_repo_url(job)

    @staticmethod
    def get_ref(job):
        return JJB.get_ref(job)


class TestSaasFileValid(TestCase):
    def setUp(self):
        self.saas_files = [
            {
                "path": "path1",
                "name": "a1",
                "managedResourceTypes": [],
                "resourceTemplates": [
                    {
                        "name": "rt",
                        "url": "url",
                        "targets": [
                            {
                                "namespace": {
                                    "name": "ns",
                                    "environment": {"name": "env1", "parameters": "{}"},
                                    "cluster": {"name": "cluster"},
                                },
                                "ref": "main",
                                "upstream": {"instance": {"name": "ci"}, "name": "job"},
                                "parameters": {},
                            },
                            {
                                "namespace": {
                                    "name": "ns",
                                    "environment": {"name": "env2", "parameters": "{}"},
                                    "cluster": {"name": "cluster"},
                                },
                                "ref": "master",
                                "upstream": {"instance": {"name": "ci"}, "name": "job"},
                                "parameters": {},
                            },
                            {
                                "namespace": {
                                    "name": "ns",
                                    "environment": {"name": "env3", "parameters": "{}"},
                                    "cluster": {"name": "cluster"},
                                },
                                "ref": "master",
                                "image": {
                                    "org": {
                                        "name": "org1",
                                        "instance": {"name": "q1"},
                                    },
                                    "name": "image",
                                },
                                "parameters": {},
                            },
                            {
                                "namespace": {
                                    "name": "ns",
                                    "environment": {"name": "env4", "parameters": "{}"},
                                    "cluster": {"name": "cluster"},
                                },
                                "ref": "2637b6c41bda7731b1bcaaf18b4a50d7c5e63e30",
                                "parameters": {},
                            },
                        ],
                    }
                ],
                "roles": [{"users": [{"org_username": "myname"}]}],
                "selfServiceRoles": [
                    {"users": [{"org_username": "theirname"}], "bots": []}
                ],
            }
        ]
        jjb_mock_data = {
            "ci": [
                {
                    "name": "job",
                    "properties": [{"github": {"url": "url"}}],
                    "scm": [{"git": {"branches": ["main"]}}],
                },
                {
                    "name": "job",
                    "properties": [{"github": {"url": "url"}}],
                    "scm": [{"git": {"branches": ["master"]}}],
                },
            ]
        }
        self.jjb = MockJJB(jjb_mock_data)

    def test_check_saas_file_env_combo_unique(self):
        saasherder = SaasHerder(
            self.saas_files,
            thread_pool_size=1,
            gitlab=None,
            integration="",
            integration_version="",
            settings={},
            validate=True,
        )

        self.assertTrue(saasherder.valid)

    def test_check_saas_file_env_combo_not_unique(self):
        self.saas_files[0][
            "name"
        ] = "long-name-which-is-too-long-to-produce-unique-combo"
        saasherder = SaasHerder(
            self.saas_files,
            thread_pool_size=1,
            gitlab=None,
            integration="",
            integration_version="",
            settings={},
            validate=True,
        )

        self.assertFalse(saasherder.valid)

    def test_saas_file_auto_promotion_used_with_commit_sha(self):
        self.saas_files[0]["resourceTemplates"][0]["targets"][3]["promotion"] = {
            "auto": True
        }
        saasherder = SaasHerder(
            self.saas_files,
            thread_pool_size=1,
            gitlab=None,
            integration="",
            integration_version="",
            settings={},
            validate=True,
        )

        self.assertTrue(saasherder.valid)

    def test_saas_file_auto_promotion_not_used_with_commit_sha(self):
        self.saas_files[0]["resourceTemplates"][0]["targets"][2]["ref"] = "main"
        self.saas_files[0]["resourceTemplates"][0]["targets"][2]["promotion"] = {
            "auto": True
        }
        saasherder = SaasHerder(
            self.saas_files,
            thread_pool_size=1,
            gitlab=None,
            integration="",
            integration_version="",
            settings={},
            validate=True,
        )

        self.assertFalse(saasherder.valid)

    def test_check_saas_file_upstream_not_used_with_commit_sha(self):
        saasherder = SaasHerder(
            self.saas_files,
            thread_pool_size=1,
            gitlab=None,
            integration="",
            integration_version="",
            settings={},
            validate=True,
        )

        self.assertTrue(saasherder.valid)

    def test_check_saas_file_upstream_used_with_commit_sha(self):
        self.saas_files[0]["resourceTemplates"][0]["targets"][0][
            "ref"
        ] = "2637b6c41bda7731b1bcaaf18b4a50d7c5e63e30"
        saasherder = SaasHerder(
            self.saas_files,
            thread_pool_size=1,
            gitlab=None,
            integration="",
            integration_version="",
            settings={},
            validate=True,
        )

        self.assertFalse(saasherder.valid)

    def test_check_saas_file_upstream_used_with_image(self):
        self.saas_files[0]["resourceTemplates"][0]["targets"][0]["image"] = "here"
        saasherder = SaasHerder(
            self.saas_files,
            thread_pool_size=1,
            gitlab=None,
            integration="",
            integration_version="",
            settings={},
            validate=True,
        )

        self.assertFalse(saasherder.valid)

    def test_check_saas_file_image_used_with_commit_sha(self):
        self.saas_files[0]["resourceTemplates"][0]["targets"][2][
            "ref"
        ] = "2637b6c41bda7731b1bcaaf18b4a50d7c5e63e30"
        saasherder = SaasHerder(
            self.saas_files,
            thread_pool_size=1,
            gitlab=None,
            integration="",
            integration_version="",
            settings={},
            validate=True,
        )

        self.assertFalse(saasherder.valid)

    def test_validate_image_tag_not_equals_ref_valid(self):
        self.saas_files[0]["resourceTemplates"][0]["targets"][0][
            "parameters"
        ] = '{"IMAGE_TAG": "2637b6c"}'
        saasherder = SaasHerder(
            self.saas_files,
            thread_pool_size=1,
            gitlab=None,
            integration="",
            integration_version="",
            settings={},
            validate=True,
        )

        self.assertTrue(saasherder.valid)

    def test_validate_image_tag_not_equals_ref_invalid(self):
        self.saas_files[0]["resourceTemplates"][0]["targets"][0][
            "ref"
        ] = "2637b6c41bda7731b1bcaaf18b4a50d7c5e63e30"
        self.saas_files[0]["resourceTemplates"][0]["targets"][0][
            "parameters"
        ] = '{"IMAGE_TAG": "2637b6c"}'
        saasherder = SaasHerder(
            self.saas_files,
            thread_pool_size=1,
            gitlab=None,
            integration="",
            integration_version="",
            settings={},
            validate=True,
        )

        self.assertFalse(saasherder.valid)

    def test_validate_upstream_jobs_valid(self):
        saasherder = SaasHerder(
            self.saas_files,
            thread_pool_size=1,
            gitlab=None,
            integration="",
            integration_version="",
            settings={},
            validate=True,
        )
        saasherder.validate_upstream_jobs(self.jjb)
        self.assertTrue(saasherder.valid)

    def test_validate_upstream_jobs_invalid(self):
        saasherder = SaasHerder(
            self.saas_files,
            thread_pool_size=1,
            gitlab=None,
            integration="",
            integration_version="",
            settings={},
            validate=True,
        )
        jjb = MockJJB({"ci": []})
        saasherder.validate_upstream_jobs(jjb)
        self.assertFalse(saasherder.valid)

    def test_check_saas_file_promotion_same_source(self):
        rts = [
            {
                "name": "rt_publisher",
                "url": "repo_publisher",
                "targets": [
                    {
                        "namespace": {
                            "name": "ns",
                            "environment": {"name": "env1"},
                            "cluster": {"name": "cluster"},
                        },
                        "parameters": {},
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
                "targets": [
                    {
                        "namespace": {
                            "name": "ns2",
                            "environment": {"name": "env1"},
                            "cluster": {"name": "cluster"},
                        },
                        "parameters": {},
                        "ref": "0000000000000",
                        "promotion": {
                            "auto": "true",
                            "subscribe": ["channel-1"],
                        },
                    }
                ],
            },
        ]
        self.saas_files[0]["resourceTemplates"] = rts
        saasherder = SaasHerder(
            self.saas_files,
            thread_pool_size=1,
            gitlab=None,
            integration="",
            integration_version="",
            settings={},
            validate=True,
        )
        self.assertFalse(saasherder.valid)


class TestGetMovingCommitsDiffSaasFile(TestCase):
    def setUp(self):
        self.saas_files = [
            {
                "path": "path1",
                "name": "a1",
                "managedResourceTypes": [],
                "resourceTemplates": [
                    {
                        "name": "rt",
                        "url": "http://github.com/user/repo",
                        "targets": [
                            {
                                "namespace": {
                                    "name": "ns",
                                    "environment": {"name": "env1"},
                                    "cluster": {"name": "cluster1"},
                                },
                                "parameters": {},
                                "ref": "main",
                            },
                            {
                                "namespace": {
                                    "name": "ns",
                                    "environment": {"name": "env2"},
                                    "cluster": {"name": "cluster2"},
                                },
                                "parameters": {},
                                "ref": "secondary",
                            },
                        ],
                    }
                ],
                "roles": [{"users": [{"org_username": "myname"}]}],
            }
        ]
        self.initiate_gh_patcher = patch.object(
            SaasHerder, "_initiate_github", autospec=True
        )
        self.get_pipelines_provider_patcher = patch.object(
            SaasHerder, "_get_pipelines_provider"
        )
        self.get_commit_sha_patcher = patch.object(
            SaasHerder, "_get_commit_sha", autospec=True
        )
        self.initiate_gh = self.initiate_gh_patcher.start()
        self.get_pipelines_provider = self.get_pipelines_provider_patcher.start()
        self.get_commit_sha = self.get_commit_sha_patcher.start()
        self.maxDiff = None

    def tearDown(self):
        for p in (
            self.initiate_gh_patcher,
            self.get_pipelines_provider_patcher,
            self.get_commit_sha_patcher,
        ):
            p.stop()

    def test_get_moving_commits_diff_saas_file_all_fine(self):
        saasherder = SaasHerder(
            self.saas_files,
            thread_pool_size=1,
            gitlab=None,
            integration="",
            integration_version="",
            settings={},
            validate=False,
        )
        saasherder.state = MagicMock()
        saasherder.state.get.return_value = "asha"
        self.get_commit_sha.side_effect = ("abcd4242", "4242efg")
        self.get_pipelines_provider.return_value = "apipelineprovider"
        expected = [
            TriggerSpecMovingCommit(
                saas_file_name=self.saas_files[0]["name"],
                env_name="env1",
                timeout=None,
                ref="main",
                state_content="abcd4242",
                cluster_name="cluster1",
                pipelines_provider="apipelineprovider",
                namespace_name="ns",
                resource_template_name="rt",
            ),
            TriggerSpecMovingCommit(
                saas_file_name=self.saas_files[0]["name"],
                env_name="env2",
                timeout=None,
                ref="secondary",
                state_content="4242efg",
                cluster_name="cluster2",
                pipelines_provider="apipelineprovider",
                namespace_name="ns",
                resource_template_name="rt",
            ),
        ]

        self.assertEqual(
            saasherder.get_moving_commits_diff_saas_file(self.saas_files[0], True),
            expected,
        )

    def test_get_moving_commits_diff_saas_file_all_fine_include_trigger_trace(self):
        saasherder = SaasHerder(
            self.saas_files,
            thread_pool_size=1,
            gitlab=None,
            integration="",
            integration_version="",
            settings={},
            validate=False,
            include_trigger_trace=True,
        )
        saasherder.state = MagicMock()
        saasherder.state.get.return_value = "asha"
        self.get_commit_sha.side_effect = ("abcd4242", "4242efg")
        self.get_pipelines_provider.return_value = "apipelineprovider"
        expected = [
            TriggerSpecMovingCommit(
                saas_file_name=self.saas_files[0]["name"],
                env_name="env1",
                timeout=None,
                ref="main",
                state_content="abcd4242",
                cluster_name="cluster1",
                pipelines_provider="apipelineprovider",
                namespace_name="ns",
                resource_template_name="rt",
                reason="http://github.com/user/repo/commit/abcd4242",
            ),
            TriggerSpecMovingCommit(
                saas_file_name=self.saas_files[0]["name"],
                env_name="env2",
                timeout=None,
                ref="secondary",
                state_content="4242efg",
                cluster_name="cluster2",
                pipelines_provider="apipelineprovider",
                namespace_name="ns",
                resource_template_name="rt",
                reason="http://github.com/user/repo/commit/4242efg",
            ),
        ]

        self.assertEqual(
            saasherder.get_moving_commits_diff_saas_file(self.saas_files[0], True),
            expected,
        )

    def test_get_moving_commits_diff_saas_file_bad_sha1(self):
        saasherder = SaasHerder(
            self.saas_files,
            thread_pool_size=1,
            gitlab=None,
            integration="",
            integration_version="",
            settings={},
            validate=False,
        )
        saasherder.state = MagicMock()
        saasherder.state.get.return_value = "asha"
        self.get_pipelines_provider.return_value = "apipelineprovider"
        self.get_commit_sha.side_effect = GithubException(
            401, "somedata", {"aheader": "avalue"}
        )
        # At least we don't crash!
        self.assertEqual(
            saasherder.get_moving_commits_diff_saas_file(self.saas_files[0], True), []
        )


class TestPopulateDesiredState(TestCase):
    def setUp(self):
        saas_files = []
        self.fxts = Fixtures("saasherder_populate_desired")
        for file in [self.fxts.get("saas_remote_openshift_template.yaml")]:
            saas_files.append(yaml.safe_load(file))

        self.assertEqual(1, len(saas_files))
        self.saasherder = SaasHerder(
            saas_files,
            thread_pool_size=1,
            gitlab=None,
            integration="",
            integration_version="",
            settings={"hashLength": 7},
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

    def fake_get_file_contents(self, options):
        self.assertEqual("https://github.com/rhobs/configuration", options["url"])

        content = self.fxts.get(options["ref"] + (options["path"].replace("/", "_")))
        return yaml.safe_load(content), "yolo", options["ref"]

    def tearDown(self):
        for p in (
            self.initiate_gh_patcher,
            self.get_file_contents_patcher,
            self.get_check_images_patcher,
        ):
            p.stop()

    def test_populate_desired_state_saas_file_delete(self):
        spec = {"delete": True}

        desired_state = self.saasherder.populate_desired_state_saas_file(spec, None)
        self.assertIsNone(desired_state)

    def test_populate_desired_state_cases(self):
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
        for (cluster, namespace, resource_type, data) in ri:
            for _, d_item in data["desired"].items():
                expected = yaml.safe_load(
                    self.fxts.get(
                        f"expected_{cluster}_{namespace}_{resource_type}.json",
                    )
                )
                self.assertEqual(expected, d_item.body)
                cnt += 1

        self.assertEqual(5, cnt, "expected 5 resources, found less")


class TestCollectRepoUrls(TestCase):
    def test_collect_repo_urls(self):
        repo_url = "git-repo"
        saas_files = [
            {
                "path": "path1",
                "name": "name1",
                "managedResourceTypes": [],
                "resourceTemplates": [{"name": "name", "url": repo_url, "targets": []}],
            }
        ]

        saasherder = SaasHerder(
            saas_files,
            thread_pool_size=1,
            gitlab=None,
            integration="",
            integration_version="",
            settings={},
        )
        self.assertEqual({repo_url}, saasherder.repo_urls)


class TestGetSaasFileAttribute(TestCase):
    def test_attribute_none(self):
        saas_files = [
            {
                "path": "path1",
                "name": "name1",
                "managedResourceTypes": [],
                "resourceTemplates": [],
            }
        ]

        saasherder = SaasHerder(
            saas_files,
            thread_pool_size=1,
            gitlab=None,
            integration="",
            integration_version="",
            settings={},
        )
        att = saasherder._get_saas_file_feature_enabled("no_such_attribute")
        self.assertEqual(att, None)

    def test_attribute_not_none(self):
        saas_files = [
            {
                "path": "path1",
                "name": "name1",
                "managedResourceTypes": [],
                "resourceTemplates": [],
                "attrib": True,
            }
        ]

        saasherder = SaasHerder(
            saas_files,
            thread_pool_size=1,
            gitlab=None,
            integration="",
            integration_version="",
            settings={},
        )
        att = saasherder._get_saas_file_feature_enabled("attrib")
        self.assertEqual(att, True)

    def test_attribute_none_with_default(self):
        saas_files = [
            {
                "path": "path1",
                "name": "name1",
                "managedResourceTypes": [],
                "resourceTemplates": [],
            }
        ]

        saasherder = SaasHerder(
            saas_files,
            thread_pool_size=1,
            gitlab=None,
            integration="",
            integration_version="",
            settings={},
        )
        att = saasherder._get_saas_file_feature_enabled("no_such_att", default=True)
        self.assertEqual(att, True)

    def test_attribute_not_none_with_default(self):
        saas_files = [
            {
                "path": "path1",
                "name": "name1",
                "managedResourceTypes": [],
                "resourceTemplates": [],
                "attrib": True,
            }
        ]

        saasherder = SaasHerder(
            saas_files,
            thread_pool_size=1,
            gitlab=None,
            integration="",
            integration_version="",
            settings={},
        )
        att = saasherder._get_saas_file_feature_enabled("attrib", default=False)
        self.assertEqual(att, True)

    def test_attribute_multiple_saas_files_return_false(self):
        saas_files = [
            {
                "path": "path1",
                "name": "name1",
                "managedResourceTypes": [],
                "resourceTemplates": [],
                "attrib": True,
            },
            {
                "path": "path2",
                "name": "name2",
                "managedResourceTypes": [],
                "resourceTemplates": [],
            },
        ]

        saasherder = SaasHerder(
            saas_files,
            thread_pool_size=1,
            gitlab=None,
            integration="",
            integration_version="",
            settings={},
        )
        self.assertFalse(saasherder._get_saas_file_feature_enabled("attrib"))

    def test_attribute_multiple_saas_files_with_default_return_false(self):
        saas_files = [
            {
                "path": "path1",
                "name": "name1",
                "managedResourceTypes": [],
                "resourceTemplates": [],
                "attrib": True,
            },
            {
                "path": "path2",
                "name": "name2",
                "managedResourceTypes": [],
                "resourceTemplates": [],
                "attrib": True,
            },
        ]

        saasherder = SaasHerder(
            saas_files,
            thread_pool_size=1,
            gitlab=None,
            integration="",
            integration_version="",
            settings={},
        )
        att = saasherder._get_saas_file_feature_enabled("attrib", default=True)
        self.assertFalse(att)


class TestConfigHashPromotionsValidation(TestCase):
    """TestCase to test SaasHerder promotions validation. SaasHerder is
    initialized with ResourceInventory population. Like is done in
    openshift-saas-deploy"""

    cluster: str
    namespace: str
    fxt: Any
    template: Any

    @classmethod
    def setUpClass(cls):
        cls.fxt = Fixtures("saasherder")
        cls.cluster = "test-cluster"
        cls.template = cls.fxt.get_anymarkup("template_1.yml")

    def setUp(self) -> None:
        self.all_saas_files = [self.fxt.get_anymarkup("saas.gql.yml")]

        self.state_patcher = patch("reconcile.utils.saasherder.State", autospec=True)
        self.state_mock = self.state_patcher.start().return_value

        self.ig_patcher = patch.object(SaasHerder, "_initiate_github", autospec=True)
        self.ig_patcher.start()

        self.image_auth_patcher = patch.object(SaasHerder, "_initiate_image_auth")
        self.image_auth_patcher.start()

        self.gfc_patcher = patch.object(SaasHerder, "_get_file_contents", autospec=True)
        gfc_mock = self.gfc_patcher.start()

        self.saas_file = self.fxt.get_anymarkup("saas.gql.yml")
        # ApiVersion is set in the saas gql query method in queries module
        self.saas_file["apiVersion"] = "v2"

        gfc_mock.return_value = (self.template, "url", "ahash")

        self.deploy_current_state_fxt = self.fxt.get_anymarkup("saas_deploy.state.json")

        self.post_deploy_current_state_fxt = self.fxt.get_anymarkup(
            "saas_post_deploy.state.json"
        )

        self.saasherder = SaasHerder(
            [self.saas_file],
            thread_pool_size=1,
            gitlab=None,
            integration="",
            integration_version="",
            accounts={"name": "test-account"},  # Initiates State in SaasHerder
            settings={"hashLength": 24},
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

    def tearDown(self):
        self.state_patcher.stop()
        self.ig_patcher.stop()
        self.gfc_patcher.stop()

    def test_config_hash_is_filled(self) -> None:
        """Ensures the get_config_diff_saas_file fills the promotion data
        on the publisher target. This data is used in publish_promotions
        method to add the hash to subscribed targets.
        IMPORTANT: This is not the promotion_data within promotion. This
        fields are set by _process_template method in saasherder
        """
        trigger_spec: TriggerSpecConfig = self.saasherder.get_configs_diff_saas_file(
            self.saas_file
        )[0]
        promotion = trigger_spec.state_content["promotion"]
        self.assertIsNotNone(promotion[TARGET_CONFIG_HASH])

    def test_promotion_state_config_hash_match_validates(self):
        """A promotion is valid if the parent target config_hash set in
        the state is equal to the one set in the subscriber target
        promotion data. This is the happy path.
        """
        publisher_state = {
            "success": True,
            "saas_file": self.saas_file["name"],
            TARGET_CONFIG_HASH: "ed2af38cf21f268c",
        }
        self.state_mock.get.return_value = publisher_state
        result = self.saasherder.validate_promotions()
        self.assertTrue(result)

    def test_promotion_state_config_hash_not_match_no_validates(self):
        """Promotion is not valid if the parent target config hash set in
        the state does not match with the one set in the subsriber target
        promotion_data. This could happen if the parent target has run again
        with the same ref before before the subscriber target promotion MR is
        merged.
        """
        publisher_state = {
            "success": True,
            "saas_file": self.saas_file["name"],
            TARGET_CONFIG_HASH: "will_not_match",
        }
        self.state_mock.get.return_value = publisher_state
        result = self.saasherder.validate_promotions()
        self.assertFalse(result)

    def test_promotion_without_state_config_hash_validates(self):
        """Existent states won't have promotion data. If there is an ongoing
        promotion, this ensures it will happen.
        """
        publisher_state = {
            "success": True,
        }
        self.state_mock.get.return_value = publisher_state
        result = self.saasherder.validate_promotions()
        self.assertTrue(result)

    def test_promotion_without_promotion_data_validates(self):
        """A manual promotion might be required, subsribed targets without
        promotion_data should validate if the parent target job has succed
        with the same ref.
        """
        publisher_state = {
            "success": True,
            "saas_file": self.saas_file["name"],
            TARGET_CONFIG_HASH: "whatever",
        }

        # Remove promotion_data on the promoted target
        self.saasherder.promotions[1]["promotion_data"] = None

        self.state_mock.get.return_value = publisher_state
        result = self.saasherder.validate_promotions()
        self.assertTrue(result)


class TestConfigHashTrigger(TestCase):
    """TestCase to test Openshift SAAS deploy configs trigger. SaasHerder is
    initialized WITHOUT ResourceInventory population. Like is done in the
    config changes trigger"""

    cluster: str
    namespace: str
    fxt: Any
    template: Any

    @classmethod
    def setUpClass(cls):
        cls.fxt = Fixtures("saasherder")
        cls.cluster = "test-cluster"

    def setUp(self) -> None:
        self.all_saas_files = [self.fxt.get_anymarkup("saas.gql.yml")]

        self.state_patcher = patch("reconcile.utils.saasherder.State", autospec=True)
        self.state_mock = self.state_patcher.start().return_value

        self.saas_file = self.fxt.get_anymarkup("saas.gql.yml")
        # ApiVersion is set in the saas gql query method in queries module
        self.saas_file["apiVersion"] = "v2"

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
            thread_pool_size=1,
            gitlab=None,
            integration="",
            integration_version="",
            accounts={"name": "test-account"},  # Initiates State in SaasHerder
            settings={"hashLength": 24},
        )

    def tearDown(self):
        self.state_patcher.stop()

    def test_same_configs_do_not_trigger(self):
        """Ensures that if the same config is found, no job is triggered
        current Config is fetched from the state
        """
        trigger_specs = self.saasherder.get_configs_diff_saas_file(self.saas_file)
        self.assertListEqual(trigger_specs, [])

    def test_config_hash_change_do_trigger(self):
        """Ensures a new job is triggered if the parent config hash changes"""
        configs = self.saasherder.get_saas_targets_config_trigger_specs(self.saas_file)

        desired_tc = list(configs.values())[1].state_content
        desired_promo_data = desired_tc["promotion"]["promotion_data"]
        desired_promo_data[0]["data"][0][TARGET_CONFIG_HASH] = "Changed"

        trigger_specs = self.saasherder.get_configs_diff_saas_file(self.saas_file)
        self.assertEqual(len(trigger_specs), 1)

    def test_non_existent_config_triggers(self):
        self.state_mock.get.side_effect = [self.deploy_current_state_fxt, None]
        trigger_specs = self.saasherder.get_configs_diff_saas_file(self.saas_file)
        self.assertEqual(len(trigger_specs), 1)


class TestRemoveNoneAttributes(TestCase):
    def testSimpleDict(self):
        input = {"a": 1, "b": {}, "d": None, "e": {"aa": "aa", "bb": None}}
        expected = {"a": 1, "b": {}, "e": {"aa": "aa"}}
        res = SaasHerder.remove_none_values(input)
        self.assertEqual(res, expected)

    def testNoneValue(self):
        input = None
        expected = {}
        res = SaasHerder.remove_none_values(input)
        self.assertEqual(res, expected)
