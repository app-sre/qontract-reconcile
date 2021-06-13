from unittest import TestCase
from unittest.mock import patch, MagicMock

from reconcile.utils.oc import OC, PodNotReadyError


class TestValidatePodReady(TestCase):
    @staticmethod
    @patch.object(OC, 'get')
    def test_validate_pod_ready_all_good(oc_get):
        oc_get.return_value = {
            'status': {
                'containerStatuses': [
                    {
                        'name': 'container1',
                        'ready': True,
                    },
                    {
                        'name': 'container2',
                        'ready': True
                    }
                ]
            }
        }
        oc = OC('server', 'token', local=True)
        oc.validate_pod_ready('namespace', 'podname')

    @patch.object(OC, 'get')
    def test_validate_pod_ready_one_missing(self, oc_get):
        oc_get.return_value = {
            'status': {
                'containerStatuses': [
                    {
                        'name': 'container1',
                        'ready': True,
                    },
                    {
                        'name': 'container2',
                        'ready': False
                    }
                ]
            }
        }

        oc = OC('server', 'token', local=True)
        with self.assertRaises(PodNotReadyError):
            # Bypass the retry stuff
            oc.validate_pod_ready.__wrapped__(oc, 'namespace', 'podname')
