import logging
import os

import requests

from reconcile import queries
from utils import threaded
from utils.oc import OC_Map
from utils.oc import StatusCodeError
from utils import secret_reader
from prometheus_client.parser import text_string_to_metric_families

LOG = logging.getLogger(__name__)
QONTRACT_INTEGRATION = 'dashdotdb-dvo'
DASHDOTDB_SECRET = os.environ.get('DASHDOTDB_SECRET',
                                  'app-sre/dashdot/auth-proxy-production')


class DashdotdbDVO:
    def __init__(self, dry_run, thread_pool_size):
        self.dry_run = dry_run
        self.thread_pool_size = thread_pool_size
        self.settings = queries.get_app_interface_settings()

        secret_content = secret_reader.read_all({'path': DASHDOTDB_SECRET},
                                                settings=self.settings)

        self.dashdotdb_url = secret_content['url']
        self.dashdotdb_user = secret_content['username']
        self.dashdotdb_pass = secret_content['password']
        self.prom_user = secret_content['prom_username']
        self.prom_pass = secret_content['prom_password']

# send metrics to dashdot
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
                LOG.error('DVO: error posting %s - %s', cluster, details)

        LOG.info('DV: cluster %s synced', cluster)
        return response

# now just a simple json fetch, does a basic blob fetch
# we can re-parse this in a future update, probably
    def promql(url, query, auth=None):

"""
Run an instant-query on the prometheus instance.
The returned structure is documented here:
https://prometheus.io/docs/prometheus/latest/querying/api/#instant-queries
:param url: base prometheus url (not the API endpoint).
:type url: string
:param query: this is a second value
:type query: string
:param auth: auth object
:type auth: requests.auth
:return: structure with the metrics
:rtype: dictionary
"""
        url = os.path.join(url, 'api/v1/query')
        if auth is None:
           auth = {}
        params = {'query': query}
        response = requests.get(url, params=params, auth=auth)
        response.raise_for_status()
        response = response.json()
        # TODO ensure len response == 1
        #return response['data']['result']
        return response

# fetch data from prometheus
@staticmethod
    def _get_deploymentvalidation(cluster, validation, oc_map):
# having issues getting dynamic list of metrics, timing out or occasionally
# not being readable
# uri: /api/v1/label/__name__/values
# so for the moment, just making this static until i get that working right
        LOG.info('DV: processing %s, %s', cluster, validation)
        oc_cli = oc_map.get(cluster)
        try:
            deploymentvalidation = promql("prometheus.".cluster.
                                          ".devshift.net",
                                          validation."{}",
                                          auth=(self.prom_user,
                                                self.prom_pass))
        except StatusCodeError:
            LOG.info('DV: Unable to fetch data for %s', cluster)
            return None
   
        if not deploymentvalidation:
            return None
    
        return {'cluster': cluster,
                'data': deploymentvalidation}


# main run
    def run(self):
        clusters = queries.get_clusters()

        oc_map = OC_Map(clusters=clusters,
                        integration=QONTRACT_INTEGRATION,
                        settings=self.settings, use_jump_host=True,
                        thread_pool_size=self.thread_pool_size)

        validation_list = ( 'operator_replica', 'operator_request_limit' )
        validations = threaded.run(func=self._get_deploymentvalidation,
                                 iterable=oc_map.clusters(),
                                 iterable=validation_list)
                                 thread_pool_size=self.thread_pool_size,
                                 oc_map=oc_map,

        threaded.run(func=self._post,
                     iterable=validations,
                     thread_pool_size=self.thread_pool_size)


def run(dry_run=False, thread_pool_size=10):
    dashdotdb_dvo = DashdotdbDVO(dry_run, thread_pool_size)
    dashdotdb_dvo.run()
