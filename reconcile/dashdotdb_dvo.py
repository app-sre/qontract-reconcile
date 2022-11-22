from dataclasses import dataclass
from typing import Any, Optional
import requests

from sretoolbox.utils import threaded
from reconcile.gql_definitions.common.clusters_minimal import ClusterV1

from reconcile.typed_queries.clusters_minimal import get_clusters_minimal
from reconcile.dashdotdb_base import DashdotdbBase, LOG

QONTRACT_INTEGRATION = "dashdotdb-dvo"


@dataclass
class DVOPayload:
    cluster_name: str
    payload: dict[Any, Any]


@dataclass
class ClusterValidationMetrics:
    cluster_name: str
    metrics: list[str]


@dataclass
class PrometheusInfo:
    url: str
    ssl_verify: bool
    token: str


class DashdotdbDVO(DashdotdbBase):
    def __init__(self, dry_run, thread_pool_size):
        super().__init__(dry_run, thread_pool_size, "DDDB_DVO:", "deploymentvalidation")
        self.chunksize = self.secret_content.get("chunksize") or "20"

    @staticmethod
    def _chunkify(data, size):
        for i in range(0, len(data), int(size)):
            yield data[i : i + int(size)]

    def _post(self, deploymentvalidation: DVOPayload):
        if deploymentvalidation is None:
            return
        cluster_name = deploymentvalidation.cluster_name
        # dvd.data.data.result.[{metric,values}]
        dvdata = deploymentvalidation.payload.get("data", {})
        if not dvdata:
            return
        dvresult = dvdata.get("result")
        if dvresult is None:
            return
        LOG.info(
            "%s Processing (%s) metrics for: %s",
            self.logmarker,
            len(dvresult),
            cluster_name,
        )
        if not self.chunksize:
            self.chunksize = str(len(dvresult))
        if len(dvresult) <= int(self.chunksize):
            metrics = dvresult
        else:
            metrics = list(self._chunkify(dvresult, self.chunksize))
            LOG.info(
                "%s Chunked metrics into (%s) elements for: %s",
                self.logmarker,
                len(metrics),
                cluster_name,
            )
        # keep everything but metrics from prom blob
        deploymentvalidation.payload["data"]["result"] = []
        response = None
        for metric_chunk in metrics:
            # to keep future-prom-format compatible,
            # keeping entire prom blob but iterating on metrics by
            # self.chunksize max metrics in one post
            dvdata = deploymentvalidation.payload

            # if metric_chunk isn't already a list, make it one
            if isinstance(metric_chunk, list):
                dvdata["data"]["result"] = metric_chunk
            else:
                dvdata["data"]["result"] = [metric_chunk]
            if not self.dry_run:
                endpoint = (
                    f"{self.dashdotdb_url}/api/v1/deploymentvalidation/{cluster_name}"
                )
                response = self._do_post(endpoint, dvdata, (5, 120))
                try:
                    response.raise_for_status()
                except requests.exceptions.RequestException as details:
                    LOG.error(
                        "%s error posting DVO data (%s): %s",
                        self.logmarker,
                        cluster_name,
                        details,
                    )

        LOG.info("%s DVO data for %s synced to DDDB", self.logmarker, cluster_name)
        return response

    def _get_deploymentvalidation(
        self, metrics: list[str], cluster: ClusterV1
    ) -> Optional[DVOPayload]:
        prom_info = self._get_prometheus_info(cluster)
        if not prom_info:
            return None
        LOG.debug("%s processing %s, %s", self.logmarker, cluster.name, metrics)

        try:
            deploymentvalidation = self._promget(
                url=prom_info.url,
                params={"query": (metrics)},
                token=prom_info.token,
                ssl_verify=prom_info.ssl_verify,
            )
        except requests.exceptions.RequestException as details:
            LOG.error(
                "%s error accessing prometheus (%s): %s",
                self.logmarker,
                cluster.name,
                details,
            )
            return None

        return DVOPayload(
            cluster_name=cluster.name,
            payload=deploymentvalidation,
        )

    # query the prometheus instance on a cluster and retrieve all the metric
    # names.  If a filter is provided, use that to filter the metric names
    # via startswith and return only those that match.
    # Returns a map of {cluster: cluster_name, data: [metric_names]}
    def _get_validation_names(
        self, cluster: ClusterV1, filter: Optional[str] = None
    ) -> Optional[ClusterValidationMetrics]:
        prom_info = self._get_prometheus_info(cluster)
        if not prom_info:
            return None
        LOG.debug(
            "%s retrieving validation names for %s, filter %s",
            self.logmarker,
            cluster.name,
            filter,
        )

        try:
            uri = "/api/v1/label/__name__/values"
            deploymentvalidation = self._promget(
                url=prom_info.url,
                params={},
                token=prom_info.token,
                ssl_verify=prom_info.ssl_verify,
                uri=uri,
            )
        except requests.exceptions.RequestException as details:
            LOG.error(
                "%s error accessing prometheus (%s): %s",
                self.logmarker,
                cluster.name,
                details,
            )
            return None

        if filter:
            deploymentvalidation["data"] = [
                n for n in deploymentvalidation["data"] if n.startswith(filter)
            ]

        return ClusterValidationMetrics(
            cluster_name=cluster.name,
            metrics=deploymentvalidation["data"],
        )

    def _get_prometheus_info(self, cluster: ClusterV1) -> Optional[PrometheusInfo]:
        if not cluster.automation_token:
            LOG.error(
                "%s cluster %s does not have an automation token",
                self.logmarker,
                cluster.name,
            )
            return None
        return PrometheusInfo(
            url=cluster.prometheus_url,
            ssl_verify=((cluster.spec or False) and cluster.spec.private),
            token=self._get_automation_token(cluster.automation_token),
        )

    @staticmethod
    def _get_clusters(name: Optional[str] = None) -> list[ClusterV1]:
        return [
            c for c in get_clusters_minimal(name=name) if c.ocm and c.prometheus_url
        ]

    def run(self, cname: Optional[str] = None):
        clusters = self._get_clusters(name=cname)
        validation_list: list[ClusterValidationMetrics] = threaded.run(
            func=self._get_validation_names,
            iterable=clusters,
            thread_pool_size=self.thread_pool_size,
            filter="deployment_validation_operator",
        )
        validation_metrics_by_cluster: dict[str, list[str]] = {}
        if validation_list:
            validation_metrics_by_cluster = {
                v.cluster_name: v.metrics for v in validation_list
            }
        self._get_token()
        for cluster in clusters:
            if cluster.name not in validation_metrics_by_cluster:
                LOG.debug("%s Skipping cluster: %s", self.logmarker, cluster.name)
                continue
            LOG.debug("%s Processing cluster: %s", self.logmarker, cluster.name)
            validations: list[DVOPayload] = threaded.run(
                func=self._get_deploymentvalidation,
                iterable=validation_metrics_by_cluster[cluster.name],
                thread_pool_size=self.thread_pool_size,
                cluster=cluster,
            )
            threaded.run(
                func=self._post,
                iterable=validations,
                thread_pool_size=self.thread_pool_size,
            )
        self._close_token()


def run(dry_run=False, thread_pool_size=10, cluster_name=None):
    dashdotdb_dvo = DashdotdbDVO(dry_run, thread_pool_size)
    dashdotdb_dvo.run(cluster_name)
