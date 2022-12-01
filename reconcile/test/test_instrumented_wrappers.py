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
