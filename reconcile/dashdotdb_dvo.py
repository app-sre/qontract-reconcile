import logging
import os
import requests

from urllib.parse import urljoin
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
        self.logmarker = "DDDB_DVO:"

    def _post(self, deploymentvalidation):
        if deploymentvalidation is None:
            return None
        cluster = deploymentvalidation['cluster']
        dvdata = deploymentvalidation['data']
        LOG.info('%s posting validations for %s', self.logmarker, cluster)
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
                LOG.error('%s error posting %s - %s',
                          self.logmarker, cluster, details)

        LOG.info('%s cluster %s synced', self.logmarker, cluster)
        return response

    def _promget(self, url, query, token=None):
        uri = 'api/v1/query'
        url = urljoin('https://'+url, uri)
        headers = {
            "accept": "application/json",
            "Authorization": "Bearer " + token,
        }
        params = {'query': query}
        LOG.info('%s Fetching prom payload from %s?%s',
                 self.logmarker, url, query)
        response = requests.get(url,
                                params=params,
                                headers=headers,
                                timeout=(5, 30))
        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError as details:
            LOG.error('%s error accessing prometheus - %s',
                      self.logmarker, details)

        response = response.json()
        # TODO ensure len response == 1
        # return response['data']['result']
        return response

    def _get_automationtoken(self, cluster):
        autotoken_reader = SecretReader(settings=self.settings)
        autotoken = {'path': "app-sre/creds/kube-configs/" + cluster,
                     'field': "token"}
        token = autotoken_reader.read(autotoken)
        return token

    def _get_deploymentvalidation(self, cluster, validation, oc_map):
        LOG.debug('%s processing %s, %s', self.logmarker, cluster, validation)
        cluster_promurl = "prometheus." + cluster + ".devshift.net"
        promquery = "deployment_validation_"+validation+"_validation"
        cluster_promuri = "query=" + promquery
        cluster_promtoken = self._get_automationtoken(cluster)
        try:
            deploymentvalidation = self._promget(url=cluster_promurl,
                                                 query=cluster_promuri,
                                                 token=cluster_promtoken)
        except StatusCodeError:
            LOG.info('%s Unable to fetch data for %s', self.logmarker, cluster)
            return None

        if not deploymentvalidation:
            return None

        return {'cluster': cluster,
                'data': deploymentvalidation}

    def run(self):
        clusters = queries.get_clusters()
        oc_map = OC_Map(clusters=clusters,
                        integration=QONTRACT_INTEGRATION,
                        settings=self.settings, use_jump_host=True,
                        thread_pool_size=self.thread_pool_size)
        validation_list = ('operator_replica', 'operator_request_limit')
        for validation in validation_list:
            LOG.debug('%s Processing validation: %s',
                      self.logmarker, validation)
            validations = threaded.run(func=self._get_deploymentvalidation,
                                       iterable=oc_map.clusters(),
                                       thread_pool_size=self.thread_pool_size,
                                       validation=validation,
                                       oc_map=oc_map)
            threaded.run(func=self._post,
                         iterable=validations,
                         thread_pool_size=self.thread_pool_size)


def run(dry_run=False, thread_pool_size=10):
    dashdotdb_dvo = DashdotdbDVO(dry_run, thread_pool_size)
    dashdotdb_dvo.run()
