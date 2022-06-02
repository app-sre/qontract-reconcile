from unittest import TestCase
from unittest.mock import patch

from prometheus_client import Counter

from sretoolbox.container import Image
import reconcile.utils.instrumented_wrappers as instrumented


class TestInstrumentedImage(TestCase):
    @patch.object(Counter, "labels")
    @patch.object(Image, "_get_manifest")
    def test_instrumented_reachout(self, getter, counter):
        i = instrumented.InstrumentedImage("aregistry/animage:atag")
        i._get_manifest()
        getter.assert_called_once_with()
        counter.assert_called_once()
        counter.return_value.inc.assert_called_once()


class TestInstrumentedCache(TestCase):
    def test_get_set(self):
        c = instrumented.InstrumentedCache("aninteg", 2, 0)
        c["lifeuniverseandeverything"] = 42
        self.assertEqual(c["lifeuniverseandeverything"], 42)

    def test_get_not_exists(self):
        c = instrumented.InstrumentedCache("aninteg", 2, 0)
        with self.assertRaises(KeyError):
            c["akeythatdoesnotexist"]

    def test_del(self):
        c = instrumented.InstrumentedCache("aninteg", 2, 0)
        c["todelete"] = 42
        self.assertEqual(c["todelete"], 42)
        del c["todelete"]
        with self.assertRaises(KeyError):
            c["todelete"]
