from unittest import TestCase

import reconcile.vault_replication as integ


class TestRunInteg(TestCase):
    def test_policy_contais_path(self):
        policy_paths = ["path1", "path2"]
        path = "path1"
        self.assertTrue(integ.policy_contains_path(path, policy_paths))

    def test_policy_contais_path_false(self):
        policy_paths = ["path2", "path3"]
        path = "path1"
        self.assertFalse(integ.policy_contains_path(path, policy_paths))

    def test_check_invalid_paths_ko(self):
        path_list = ["path1", "path3"]
        policy_paths = ["path1", "path2"]
        with self.assertRaises(integ.VaultInvalidPaths):
            integ.check_invalid_paths(path_list, policy_paths)

    def test_check_invalid_paths_ok(self):
        path_list = ["path1", "path2"]
        policy_paths = ["path1", "path2"]
        integ.check_invalid_paths(path_list, policy_paths)

    def test_list_invalid_paths(self):
        path_list = ["path1", "path3"]
        policy_paths = ["path1", "path2"]
        self.assertEqual(integ.list_invalid_paths(path_list, policy_paths), ["path3"])
