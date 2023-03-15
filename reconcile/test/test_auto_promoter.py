from unittest import TestCase

from reconcile.utils.mr.auto_promoter import (
    TARGET_CONFIG_HASH,
    AutoPromoter,
    ParentSaasConfigPromotion,
)

# from unittest.mock import MagicMock


# from .fixtures import Fixtures


class TestPromotions(TestCase):
    def test_init_promotion_data(self):
        promotion = {
            "commit_sha": "ahash",
            "saas_file": "saas_file",
            "target_config_hash": "123123123",
        }

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

    def test_init_parent_saas_config_dataclass(self):
        data = {
            "parent_saas": "saas_file",
            TARGET_CONFIG_HASH: "123123123",
            "type": "parent_saas_config",
        }

        obj = ParentSaasConfigPromotion(**data)
        self.assertEqual(obj.type, ParentSaasConfigPromotion.TYPE)
        self.assertEqual(obj.target_config_hash, data[TARGET_CONFIG_HASH])
        self.assertEqual(obj.parent_saas, data["parent_saas"])

    def test_process_promotion_init_promotion_data(self):
        promotion = {
            "saas_file_paths": ["destination-saas-file"],
            "auto": True,
            "publish": ["test-channel"],
            "commit_sha": "ahash",
            "saas_file": "saas_file",
            TARGET_CONFIG_HASH: "111111111",
        }

        target_promotion = {
            "auto": True,
            "subscribe": ["test-channel"],
        }

        modified = AutoPromoter.process_promotion(
            promotion, target_promotion, ["test-channel"]
        )
        self.assertTrue(modified)

        tp = target_promotion["promotion_data"][0]
        tp_hash = tp["data"][0]["target_config_hash"]
        self.assertEqual(tp_hash, "111111111")

    def test_process_promotion_update_when_config_hash_changes(self):
        promotion = {
            "saas_file_paths": ["destination-saas-file"],
            "auto": True,
            "publish": ["test-channel"],
            "commit_sha": "ahash",
            "saas_file": "saas_file",
            TARGET_CONFIG_HASH: "111111111",
        }

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

        tp = target_promotion["promotion_data"][0]
        tp_hash = tp["data"][0]["target_config_hash"]
        self.assertEqual(tp_hash, "111111111")

    def test_process_promotion_dont_update_when_equal_config_hashes(self):
        promotion = {
            "saas_file_paths": ["destination-saas-file"],
            "auto": True,
            "publish": ["test-channel"],
            "commit_sha": "ahash",
            "saas_file": "saas_file",
            TARGET_CONFIG_HASH: "111111111",
        }

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
