from unittest import TestCase

import reconcile.utils.data_structures as ds


class TestGetOrInit(TestCase):
    def test_get_or_init_get(self):
        d = {"k": "v"}
        self.assertEqual(ds.get_or_init(d, "k", "notv"), "v")

    def test_get_or_init_init(self):
        d = {}
        self.assertEqual(ds.get_or_init(d, "k", "v"), "v")
