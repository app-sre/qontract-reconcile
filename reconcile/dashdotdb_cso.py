import requests
from sretoolbox.utils import threaded

from reconcile import queries
from reconcile.dashdotdb_base import (
    LOG,
    DashdotdbBase,
)
from reconcile.utils.oc import (
    OC_Map,
    StatusCodeError,
)

QONTRACT_INTEGRATION = "dashdotdb-cso"
LOGMARKER = "DDDB_CSO:"


class DashdotdbCSO(DashdotdbBase):
    def __init__(self, dry_run, thread_pool_size):
        super().__init__(dry_run, thread_pool_size, LOGMARKER, "imagemanifestvuln")

    def _post(self, manifest):
        if manifest is None:
            return None

        cluster = manifest["cluster"]
        imagemanifestvuln = manifest["data"]

        response = None

        LOG.info("%s syncing cluster %s", self.logmarker, cluster)

        if self.dry_run:
            return response

        for item in imagemanifestvuln["items"]:
            endpoint = f"{self.dashdotdb_url}/api/v1/" f"imagemanifestvuln/{cluster}"
            response = self._do_post(endpoint, item)
            try:
                response.raise_for_status()
            except requests.exceptions.HTTPError as details:
                LOG.error("%s error posting %s - %s", self.logmarker, cluster, details)

        LOG.info("%s cluster %s synced", self.logmarker, cluster)
        return response

    @staticmethod
    def _get_imagemanifestvuln(cluster, oc_map):
        LOG.info("%s processing %s", LOGMARKER, cluster)
        oc = oc_map.get(cluster)
        if not oc:
            LOG.log(level=oc.log_level, msg=oc.message)
            return None

        try:
            imagemanifestvuln = oc.get_all("ImageManifestVuln", all_namespaces=True)
        except StatusCodeError:
            LOG.info("%s not installed on %s", LOGMARKER, cluster)
            return None

        if not imagemanifestvuln:
            return None

        return {"cluster": cluster, "data": imagemanifestvuln}

    def run(self):
        clusters = queries.get_clusters()

        oc_map = OC_Map(
            clusters=clusters,
            integration=QONTRACT_INTEGRATION,
            settings=self.settings,
            use_jump_host=True,
            thread_pool_size=self.thread_pool_size,
        )

        manifests = threaded.run(
            func=self._get_imagemanifestvuln,
            iterable=oc_map.clusters(),
            thread_pool_size=self.thread_pool_size,
            oc_map=oc_map,
        )

        self._get_token()
        threaded.run(
            func=self._post, iterable=manifests, thread_pool_size=self.thread_pool_size
        )
        self._close_token()


def run(dry_run=False, thread_pool_size=10):
    dashdotdb_cso = DashdotdbCSO(dry_run, thread_pool_size)
    dashdotdb_cso.run()
