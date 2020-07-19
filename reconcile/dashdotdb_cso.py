import logging
import os

import requests

from reconcile import queries
from utils import threaded
from utils.oc import OC_Map
from utils.oc import StatusCodeError
from utils import secret_reader


LOG = logging.getLogger(__name__)
QONTRACT_INTEGRATION = 'dashdotdb-cso'


DASHDOTDB_SECRET = os.environ.get('DASHDOTDB_SECRET',
                                  'app-sre/dashdot/dashdotdb-production')


class DashdotdbCSO:
    def __init__(self, dry_run, thread_pool_size):
        self.dry_run = dry_run
        self.thread_pool_size = thread_pool_size
        self.settings = queries.get_app_interface_settings()

        secret_content = secret_reader.read_all({'path': DASHDOTDB_SECRET},
                                                settings=self.settings)

        self.dashdotdb_url = secret_content['API_URL']
        self.dashdotdb_token = secret_content['ACCESS_TOKEN']

    def _post(self, manifest):
        if manifest is None:
            return None

        cluster = manifest['cluster']
        imagemanifestvuln = manifest['data']

        response = None
        if not self.dry_run:
            endpoint = (f'{self.dashdotdb_url}/api/v1/'
                        f'imagemanifestvuln/{cluster}')
            headers = {'Authorization': f'token {self.dashdotdb_token}'}

            response = requests.post(url=endpoint, json=imagemanifestvuln,
                                     headers=headers)
            try:
                response.raise_for_status()
            except requests.exceptions.HTTPError as details:
                LOG.error('CSO: error posting %s - %s', cluster, details)

        LOG.info('CSO: cluster %s synced', cluster)
        return response

    @staticmethod
    def _get_imagemanifestvuln(cluster, oc_map):
        LOG.info('CSO: processing %s', cluster)
        oc_cli = oc_map.get(cluster)

        try:
            imagemanifestvuln = oc_cli.get_all('imagemanifestvuln',
                                               all_namespaces=True)
        except StatusCodeError:
            LOG.info('CSO: not installed on %s', cluster)
            return None

        if not imagemanifestvuln:
            return None

        return {'cluster': cluster,
                'data': imagemanifestvuln}

    def run(self):
        clusters = queries.get_clusters()

        oc_map = OC_Map(clusters=clusters,
                        integration=QONTRACT_INTEGRATION,
                        settings=self.settings, use_jump_host=True,
                        thread_pool_size=self.thread_pool_size)

        manifests = threaded.run(func=self._get_imagemanifestvuln,
                                 iterable=oc_map.clusters(),
                                 thread_pool_size=self.thread_pool_size,
                                 oc_map=oc_map)

        threaded.run(func=self._post,
                     iterable=manifests,
                     thread_pool_size=self.thread_pool_size)


def run(dry_run=False, thread_pool_size=10):
    dashdotdb_cso = DashdotdbCSO(dry_run, thread_pool_size)
    dashdotdb_cso.run()
