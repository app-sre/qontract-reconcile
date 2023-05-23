import json
from unittest import TestCase

from reconcile.utils.mr.auto_promoter import (
    AutoPromoter,
    ParentSaasConfigPromotion,
)
from reconcile.utils.saasherder.models import Promotion
from reconcile.utils.saasherder.saasherder import TARGET_CONFIG_HASH


class TestPromotions(TestCase):
    def test_init_promotion_data(self) -> None:
        promotion = Promotion(
            commit_sha="ahash",
            saas_file="saas_file",
            target_config_hash="123123123",
        )

        expected = {
            "channel": "test-channel",
            "data": [
                {
                    "parent_saas": "saas_file",
                    "target_config_hash": "123123123",
                    "type": "parent_saas_config",
                }
            ],
        }
        ret = AutoPromoter.init_promotion_data("test-channel", promotion)
        self.assertEqual(ret, expected)

    def test_init_parent_saas_config_dataclass(self) -> None:
        data = {
            "parent_saas": "saas_file",
            TARGET_CONFIG_HASH: "123123123",
            "type": "parent_saas_config",
        }

        obj = ParentSaasConfigPromotion(**data)
        self.assertEqual(obj.type, ParentSaasConfigPromotion.TYPE)
        self.assertEqual(obj.target_config_hash, data[TARGET_CONFIG_HASH])
        self.assertEqual(obj.parent_saas, data["parent_saas"])

    def test_process_promotion_init_promotion_data(self) -> None:
        promotion = Promotion(
            saas_file="saas_file",
            saas_file_paths=["destination-saas-file"],
            auto=True,
            publish=["test-channel"],
            commit_sha="ahash",
            target_config_hash="111111111",
        )

        target_promotion = {
            "auto": True,
            "subscribe": ["test-channel"],
        }

        modified = AutoPromoter.process_promotion(
            promotion, target_promotion, ["test-channel"]
        )
        self.assertTrue(modified)

        tp = target_promotion["promotion_data"][0]  # type: ignore
        tp_hash = tp["data"][0]["target_config_hash"]
        self.assertEqual(tp_hash, "111111111")

    def test_process_promotion_update_when_config_hash_changes(self) -> None:
        promotion = Promotion(
            saas_file_paths=["destination-saas-file"],
            auto=True,
            publish=["test-channel"],
            commit_sha="ahash",
            saas_file="saas_file",
            target_config_hash="111111111",
        )

        target_promotion = {
            "auto": True,
            "subscribe": ["test-channel"],
            "promotion_data": [
                {
                    "channel": "test-channel",
                    "data": [
                        {
                            "parent_saas": "saas_file",
                            "target_config_hash": "123123123",
                            "type": "parent_saas_config",
                        }
                    ],
                }
            ],
        }

        modified = AutoPromoter.process_promotion(
            promotion, target_promotion, ["test-channel"]
        )
        self.assertTrue(modified)

        tp = target_promotion["promotion_data"][0]  # type: ignore
        tp_hash = tp["data"][0]["target_config_hash"]
        self.assertEqual(tp_hash, "111111111")

    def test_process_promotion_dont_update_when_equal_config_hashes(self) -> None:
        promotion = Promotion(
            saas_file_paths=["destination-saas-file"],
            auto=True,
            publish=["test-channel"],
            commit_sha="ahash",
            saas_file="saas_file",
            target_config_hash="111111111",
        )

        target_promotion = {
            "auto": True,
            "subscribe": ["test-channel"],
            "promotion_data": [
                {
                    "channel": "test-channel",
                    "data": [
                        {
                            "parent_saas": "saas_file",
                            "target_config_hash": "111111111",
                            "type": "parent_saas_config",
                        }
                    ],
                }
            ],
        }

        modified = AutoPromoter.process_promotion(
            promotion, target_promotion, ["test-channel"]
        )
        self.assertFalse(modified)

    def test_title_property(self) -> None:
        promotion = Promotion(
            saas_file_paths=["destination-saas-file"],
            auto=True,
            publish=["test-channel"],
            commit_sha="ahash",
            saas_file="saas_file",
            target_config_hash="111111111",
        )

        ap = AutoPromoter([promotion])
        self.assertEqual(
            ap.title, "[auto_promoter] openshift-saas-deploy automated promotion 4af7b1"
        )

    def test_description_property(self) -> None:
        promotion = Promotion(
            saas_file_paths=["destination-saas-file"],
            auto=True,
            publish=["test-channel"],
            commit_sha="ahash",
            saas_file="saas_file",
            target_config_hash="111111111",
        )

        ap = AutoPromoter([promotion])
        self.assertEqual(ap.description, "openshift-saas-deploy automated promotion")

    def test_gitlab_data_property(self) -> None:
        promotion = Promotion(
            saas_file_paths=["destination-saas-file"],
            auto=True,
            publish=["test-channel"],
            commit_sha="ahash",
            saas_file="saas_file",
            target_config_hash="111111111",
        )

        ap = AutoPromoter([promotion])
        self.assertTrue(ap.gitlab_data["source_branch"].startswith("auto_promoter-"))
        self.assertEqual(ap.gitlab_data["target_branch"], "master")
        self.assertEqual(
            ap.gitlab_data["title"],
            "[auto_promoter] openshift-saas-deploy automated promotion 4af7b1",
        )
        self.assertEqual(
            ap.gitlab_data["description"], "openshift-saas-deploy automated promotion"
        )
        self.assertEqual(ap.gitlab_data["remove_source_branch"], True)
        self.assertEqual(ap.gitlab_data["labels"], ["bot/automerge"])

    def test_sqs_data_property(self) -> None:
        promotion = Promotion(
            saas_file_paths=["destination-saas-file"],
            auto=True,
            publish=["test-channel"],
            commit_sha="ahash",
            saas_file="saas_file",
            target_config_hash="111111111",
        )

        ap = AutoPromoter([promotion])
        self.assertEqual(
            ap.sqs_data,
            {
                "pr_type": "auto_promoter",
                "promotions": [
                    {
                        "commit_sha": "ahash",
                        "saas_file": "saas_file",
                        "target_config_hash": "111111111",
                        "auto": True,
                        "publish": ["test-channel"],
                        "subscribe": None,
                        "promotion_data": None,
                        "saas_file_paths": ["destination-saas-file"],
                        "target_paths": None,
                    }
                ],
            },
        )

    def test_sqs_data_json_serializable(self) -> None:
        promotion = Promotion(
            saas_file_paths=["destination-saas-file"],
            auto=True,
            publish=["test-channel"],
            commit_sha="ahash",
            saas_file="saas_file",
            target_config_hash="111111111",
            promotion_data=[
                {
                    "channel": "test-channel",
                    "data": [
                        {
                            "parent_saas": "saas_file",
                            "target_config_hash": "111111111",
                            "type": "parent_saas_config",
                        }
                    ],
                }
            ],
        )

        ap = AutoPromoter([promotion])
        sqs_json = '{"pr_type": "auto_promoter", "promotions": [{"commit_sha": "ahash", "saas_file": "saas_file", "target_config_hash": "111111111", "auto": true, "publish": ["test-channel"], "subscribe": null, "promotion_data": [{"channel": "test-channel", "data": [{"type": "parent_saas_config", "parent_saas": "saas_file", "target_config_hash": "111111111"}]}], "saas_file_paths": ["destination-saas-file"], "target_paths": null}]}'
        self.assertEqual(json.dumps(ap.sqs_data), sqs_json)

    def test_init_with_promotion_object(self) -> None:
        promotion = Promotion(
            saas_file_paths=["destination-saas-file"],
            auto=True,
            publish=["test-channel"],
            commit_sha="ahash",
            saas_file="saas_file",
            target_config_hash="111111111",
            promotion_data=[
                {
                    "channel": "test-channel",
                    "data": [
                        {
                            "parent_saas": "saas_file",
                            "target_config_hash": "111111111",
                            "type": "parent_saas_config",
                        }
                    ],
                }
            ],
        )

        ap = AutoPromoter([promotion])
        self.assertEqual(ap.promotions, [promotion.dict(by_alias=True)])
        self.assertEqual(ap._promotions, [promotion])

    def test_init_with_dict_object(self) -> None:
        promotion = Promotion(
            saas_file_paths=["destination-saas-file"],
            auto=True,
            publish=["test-channel"],
            commit_sha="ahash",
            saas_file="saas_file",
            target_config_hash="111111111",
            promotion_data=[
                {
                    "channel": "test-channel",
                    "data": [
                        {
                            "parent_saas": "saas_file",
                            "target_config_hash": "111111111",
                            "type": "parent_saas_config",
                        }
                    ],
                }
            ],
        )

        ap = AutoPromoter([promotion.dict(by_alias=True)])
        self.assertEqual(ap.promotions, [promotion.dict(by_alias=True)])
        self.assertEqual(ap._promotions, [promotion])
