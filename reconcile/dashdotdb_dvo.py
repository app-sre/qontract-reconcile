import logging
import os

from urllib.parse import urljoin

import requests

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
        self.chunksize = secret_content.get('chunksize') or '20'
        self.logmarker = "DDDB_DVO:"

    @staticmethod
    def _chunkify(data, size):
        for i in range(0, len(data), int(size)):
            yield data[i:i+int(size)]

    def _post(self, deploymentvalidation):
        if deploymentvalidation is None:
            return
        cluster = deploymentvalidation['cluster']
        # dvd.data.data.result.[{metric,values}]
        dvresult = deploymentvalidation.get('data').get('data').get('result')
        if dvresult is None:
            return
        LOG.info('%s Processing (%s) metrics for: %s', self.logmarker,
                 len(dvresult),
                 cluster)
        if not self.chunksize:
            self.chunksize = len(dvresult)
        if len(dvresult) <= int(self.chunksize):
            metrics = dvresult
        else:
            metrics = list(self._chunkify(dvresult, self.chunksize))
            LOG.info('%s Chunked metrics into (%s) elements for: %s',
                     self.logmarker,
                     len(metrics),
                     cluster)
        # keep everything but metrics from prom blob
        deploymentvalidation['data']['data']['result'] = []
        response = None
        for metric_chunk in metrics:
            # to keep future-prom-format compatible,
            # keeping entire prom blob but iterating on metrics by
            # self.chunksize max metrics in one post
            dvdata = deploymentvalidation['data']
            dvdata['data']['result'] = metric_chunk
            if not self.dry_run:
                endpoint = (f'{self.dashdotdb_url}/api/v1/'
                            f'deploymentvalidation/{cluster}')
                response = requests.post(url=endpoint, json=dvdata,
                                         auth=(self.dashdotdb_user,
                                               self.dashdotdb_pass),
                                         timeout=(5, 120))
                try:
                    response.raise_for_status()
                except requests.exceptions.RequestException as details:
                    LOG.error('%s error posting DVO data (%s): %s',
                              self.logmarker, cluster, details)

        LOG.info('%s DVO data for %s synced to DDDB', self.logmarker, cluster)
        return response

    def _promget(self, url, query, token=None, ssl_verify=True):
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
                                verify=ssl_verify,
                                timeout=(5, 120))
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
        ssl_verify = False if clusterinfo['private'] else True
        promquery = (f'deployment_validation_{validation}_validation')
        promtoken = self._get_automationtoken(clusterinfo['tokenpath'])
        try:
            deploymentvalidation = self._promget(url=promurl,
                                                 query=promquery,
                                                 token=promtoken,
                                                 ssl_verify=ssl_verify)
        except requests.exceptions.RequestException as details:
            LOG.error('%s error accessing prometheus (%s): %s',
                      self.logmarker, cluster, details)
            return None

        return {'cluster': cluster,
                'data': deploymentvalidation}

    @staticmethod
    def _get_clusters(cnfilter=None):
        # 'cluster': 'fooname'
        # 'private': False
        # 'prometheus': 'https://prometheus.baz.tld'
        # 'tokenpath':
        #  'path': 'app-sre/creds/kubeube-configs/barpath'
        #  'field': 'token', 'format': None}
        results = []
        clusters = queries.get_clusters(minimal=True)
        for i in clusters or []:
            if i.get('ocm') is not None and i.get('prometheusUrl') is not None:
                results.append({
                    "name": i['name'],
                    "tokenpath": i['automationToken'],
                    "private": i['spec']['private'] or False,
                    "prometheus": i['prometheusUrl']
                })
        if cnfilter:
            return [result for result in results if result['name'] == cnfilter]
        return results

    def run(self, cname=None):
        validation_list = ('operator_replica', 'operator_request_limit')
        for validation in validation_list:
            LOG.debug('%s Processing validation: %s',
                      self.logmarker, validation)
            validations = threaded.run(func=self._get_deploymentvalidation,
                                       iterable=self._get_clusters(cname),
                                       thread_pool_size=self.thread_pool_size,
                                       validation=validation)
            threaded.run(func=self._post,
                         iterable=validations,
                         thread_pool_size=self.thread_pool_size)


def run(dry_run=False, thread_pool_size=10, cluster_name=None):
    dashdotdb_dvo = DashdotdbDVO(dry_run, thread_pool_size)
    dashdotdb_dvo.run(cluster_name)
