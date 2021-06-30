from unittest import TestCase
from unittest.mock import patch

from sretoolbox.container import Image
import reconcile.utils.instrumented_wrappers as instrumented


class TestInstrumentedImage(TestCase):
    @patch.object(instrumented.InstrumentedImage._registry_reachouts, 'inc')
    @patch.object(Image, '_request_get')
    def test_instrumented_reachout(self, getter, counter):
        i = instrumented.InstrumentedImage('aregistry/animage:atag')
        i._request_get("http://localhost")
        getter.assert_called_once_with("http://localhost")
        counter.assert_called_once()
