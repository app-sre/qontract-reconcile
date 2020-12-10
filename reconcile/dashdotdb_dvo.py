import logging
import os

import requests

from reconcile import queries
from utils import threaded
from utils.oc import OC_Map
from utils.oc import StatusCodeError
from utils.secret_reader import SecretReader

LOG = logging.getLogger(__name__)
QONTRACT_INTEGRATION = 'dashdotdb-dvo'
DASHDOTDB_SECRET = os.environ.get('DASHDOTDB_SECRET',
                                  'app-sre/dashdot/auth-proxy-production')


class DashdotdbDVO:
    def __init__(self, dry_run, thread_pool_size):
        self.dry_run = dry_run
        self.thread_pool_size = thread_pool_size
        self.settings = queries.get_app_interface_settings()
        secret_reader = SecretReader(settings=self.settings)
        secret_content = secret_reader.read_all({'path': DASHDOTDB_SECRET})
        self.dashdotdb_url = secret_content['url']
        self.dashdotdb_user = secret_content['username']
        self.dashdotdb_pass = secret_content['password']
        # self.prom_pass = secret_content['prom_password']

    def _post(self, deploymentvalidation):
        if deploymentvalidation is None:
            return None

        cluster = deploymentvalidation['cluster']
        dvdata = deploymentvalidation['data']
        response = None
        if not self.dry_run:
            endpoint = (f'{self.dashdotdb_url}/api/v1/'
                        f'deploymentvalidation/{cluster}')
            response = requests.post(url=endpoint, json=dvdata,
                                     auth=(self.dashdotdb_user,
                                           self.dashdotdb_pass))
            try:
                response.raise_for_status()
            except requests.exceptions.HTTPError as details:
                LOG.error('DV: error posting %s - %s', cluster, details)

        LOG.info('DV: cluster %s synced', cluster)
        return response

    def promql(url, query, auth=None, token=None):
        url = os.path.join(url, 'api/v1/query')
        if auth is None:
            auth = {}
        params = {'query': query}
        if token:
            auth = requests.auth.AuthBase()
            auth.headers["authorization"] = "Bearer " + token
        response = requests.get(url, params=params, auth=auth)
        response.raise_for_status()
        response = response.json()
        # TODO ensure len response == 1
        # return response['data']['result']
        return response

    def _get_deploymentvalidation(self, cluster, validation, oc_map):
        LOG.info('DV: processing %s, %s', cluster, validation)

        try:
            deploymentvalidation = self.promql("prometheus." + cluster +
                                               ".devshift.net",
                                               validation + "{}",
                                               auth=(self.prom_user,
                                                     self.prom_pass))
        except StatusCodeError:
            LOG.info('DV: Unable to fetch data for %s', cluster)
            return None

        if not deploymentvalidation:
            return None

        return {'cluster': cluster,
                'data': deploymentvalidation}

    def run(self):
        LOG.debug('DV: zzzz')
        clusters = queries.get_clusters()
        LOG.debug('DV: a1')
        oc_map = OC_Map(clusters=clusters,
                        integration=QONTRACT_INTEGRATION,
                        settings=self.settings, use_jump_host=True,
                        thread_pool_size=self.thread_pool_size)
        print("%s".format(oc_map))
        LOG.debug('DV: a2')
        validation_list = ('operator_replica', 'operator_request_limit')
        LOG.debug('DV: a3')
        for validation in validation_list:
            LOG.debug('Processing validation: %s', validation)
            LOG.debug('DV: a4')
            validations = threaded.run(func=self._get_deploymentvalidation,
                                       iterable=oc_map.clusters(),
                                       thread_pool_size=self.thread_pool_size,
                                       validation=validation,
                                       oc_map=oc_map)
            LOG.debug('DV: a5')
            threaded.run(func=self._post,
                         iterable=validations,
                         thread_pool_size=self.thread_pool_size)


def run(dry_run=False, thread_pool_size=10):
    dashdotdb_dvo = DashdotdbDVO(dry_run, thread_pool_size)
    dashdotdb_dvo.run()
