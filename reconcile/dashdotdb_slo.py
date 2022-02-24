import jinja2
import requests

from sretoolbox.utils import threaded

from reconcile import queries
from reconcile.dashdotdb_base import DashdotdbBase, LOG


QONTRACT_INTEGRATION = "dashdotdb-slo"


class DashdotdbSLO(DashdotdbBase):
    def __init__(self, dry_run, thread_pool_size):
        super().__init__(dry_run, thread_pool_size, "DDDB_SLO:", "serviceslometrics")

    def _post(self, service_slo):
        if service_slo is None:
            return None

        for item in service_slo:
            LOG.debug(f"About to POST SLO JSON item to dashdotDB:\n{item}\n")

        response = None

        if self.dry_run:
            return response

        for item in service_slo:
            slo_name = item["name"]
            LOG.info("%s syncing slo %s", self.logmarker, slo_name)
            endpoint = f"{self.dashdotdb_url}/api/v1/" f"serviceslometrics/{slo_name}"
            response = self._do_post(endpoint, item)
            try:
                response.raise_for_status()
            except requests.exceptions.HTTPError as details:
                LOG.error("%s error posting %s - %s", self.logmarker, slo_name, details)

            LOG.info("%s slo %s synced", self.logmarker, slo_name)
        return response

    def _get_service_slo(self, slo_document):
        LOG.debug("SLO: processing %s", slo_document["name"])
        result = []
        for ns in slo_document["namespaces"]:
            if not ns["cluster"].get("prometheusUrl"):
                continue
            promurl = ns["cluster"]["prometheusUrl"]
            ssl_verify = False if ns["cluster"]["spec"]["private"] else True
            promtoken = self._get_automationtoken(ns["cluster"]["automationToken"])
            for slo in slo_document["slos"]:
                unit = slo["SLOTargetUnit"]
                expr = slo["expr"]
                template = jinja2.Template(expr)
                window = slo["SLOParameters"]["window"]
                promquery = template.render({"window": window})
                prom_response = self._promget(
                    url=promurl,
                    params={"query": (f"{promquery}")},
                    token=promtoken,
                    ssl_verify=ssl_verify,
                )
                prom_result = prom_response["data"]["result"]
                if not prom_result:
                    continue

                slo_value = prom_result[0]["value"]
                if not slo_value:
                    continue

                slo_value = float(slo_value[1])
                slo_target = float(slo["SLOTarget"])

                # In Dash.DB we want to always store SLOs in percentages
                if unit == "percent_0_1":
                    slo_value *= 100
                    slo_target *= 100

                result.append(
                    {
                        "name": slo["name"],
                        "SLIType": slo["SLIType"],
                        "namespace": ns,
                        "cluster": ns["cluster"],
                        "service": ns["app"],
                        "value": slo_value,
                        "target": slo_target,
                        "SLODoc": {"name": slo_document["name"]},
                    }
                )
        return result

    def run(self):
        slo_documents = queries.get_slo_documents()

        service_slos = threaded.run(
            func=self._get_service_slo,
            iterable=slo_documents,
            thread_pool_size=self.thread_pool_size,
        )

        self._get_token()
        threaded.run(
            func=self._post,
            iterable=service_slos,
            thread_pool_size=self.thread_pool_size,
        )
        self._close_token()


def run(dry_run=False, thread_pool_size=10):
    dashdotdb_slo = DashdotdbSLO(dry_run, thread_pool_size)
    dashdotdb_slo.run()
