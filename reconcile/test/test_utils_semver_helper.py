from unittest import TestCase

import reconcile.utils.semver_helper as svh


class TestSortVersions(TestCase):
    def test_sort_versions(self):
        versions = ["4.8.0", "4.8.0-rc.0", "4.8.0-fc.1", "4.8.1", "4.8.0-rc.2"]
        expected = ["4.8.0-fc.1", "4.8.0-rc.0", "4.8.0-rc.2", "4.8.0", "4.8.1"]
        self.assertEqual(expected, svh.sort_versions(versions))
