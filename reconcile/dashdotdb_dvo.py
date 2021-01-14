import logging
import os
import requests
from urllib.parse import urljoin

import reconcile.utils.threaded as threaded
import reconcile.queries as queries
from reconcile.utils.secret_reader import SecretReader

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
                                           self.dashdotdb_pass),
                                     timeout=(5, 30))
            try:
                response.raise_for_status()
            except requests.exceptions.RequestException as details:
                LOG.error('%s error posting %s - %s',
                          self.logmarker, cluster, details)

        LOG.info('%s cluster %s synced', self.logmarker, cluster)
        return response

    def _promget(self, url, query, token=None):
        uri = '/api/v1/query'
        url = urljoin((f'{url}'), uri)
        params = {'query': (f'{query}')}
        LOG.debug('%s Fetching prom payload from %s?%s',
                  self.logmarker, url, params)
        headers = {
                   "accept": "application/json",
                  }
        if token:
            headers["Authorization"] = (f"Bearer {token}")
        response = requests.get(url,
                                params=params,
                                headers=headers,
                                timeout=(5, 30))
        response.raise_for_status()

        response = response.json()
        # TODO ensure len response == 1
        # return response['data']['result']
        return response

    def _get_automationtoken(self, tokenpath):
        autotoken_reader = SecretReader(settings=self.settings)
        token = autotoken_reader.read(tokenpath)
        return token

    def _get_deploymentvalidation(self, clusterinfo, validation):
        cluster = clusterinfo['name']
        LOG.debug('%s processing %s, %s', self.logmarker, cluster, validation)
        promurl = clusterinfo['prometheus']
        promquery = (f'deployment_validation_{validation}_validation')
        promtoken = self._get_automationtoken(clusterinfo['tokenpath'])
        try:
            deploymentvalidation = self._promget(url=promurl,
                                                 query=promquery,
                                                 token=promtoken)
        except requests.exceptions.RequestException as details:
            LOG.error('%s error accessing prometheus - %s, %s',
                      self.logmarker, cluster, details)
            return None

        return {'cluster': cluster,
                'data': deploymentvalidation}

    def _get_clusters(self):
        # 'cluster': 'fooname',
        # 'tokenpath':
        #  'path': 'app-sre/creds/kubeube-configs/barpath',
        #  'field': 'token', 'format': None},
        # 'prometheus': 'https://prometheus.baz.tld'
        results = []
        clusters = queries.get_clusters(minimal=True)
        for i in clusters or []:
            if i.get('ocm') is not None and i.get('prometheusUrl') is not None:
                results.append({
                    "name": i['name'],
                    "tokenpath": i['automationToken'],
                    "prometheus": i['prometheusUrl']
                })
        return results

    def run(self):
        validation_list = ('operator_replica', 'operator_request_limit')
        for validation in validation_list:
            LOG.debug('%s Processing validation: %s',
                      self.logmarker, validation)
            validations = threaded.run(func=self._get_deploymentvalidation,
                                       iterable=self._get_clusters(),
                                       thread_pool_size=self.thread_pool_size,
                                       validation=validation)
            threaded.run(func=self._post,
                         iterable=validations,
                         thread_pool_size=self.thread_pool_size)


def run(dry_run=False, thread_pool_size=10):
    dashdotdb_dvo = DashdotdbDVO(dry_run, thread_pool_size)
    dashdotdb_dvo.run()
