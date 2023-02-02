from typing import (
    Any,
    Optional,
)

import requests
from sretoolbox.utils import threaded

from reconcile import queries
from reconcile.dashdotdb_base import (
    LOG,
    DashdotdbBase,
)
from reconcile.gql_definitions.common.clusters import ClusterV1
from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.typed_queries.clusters import get_clusters
from reconcile.utils.oc import (
    OC_Map,
    StatusCodeError,
)
from reconcile.utils.oc_connection_parameters import (
    get_oc_connection_parameters_from_clusters,
)
from reconcile.utils.oc_map import OCMap
from reconcile.utils.secret_reader import (
    SecretReaderBase,
    create_secret_reader,
)

QONTRACT_INTEGRATION = "dashdotdb-cso"
LOGMARKER = "DDDB_CSO:"


class DashdotdbCSO(DashdotdbBase):
    def __init__(
        self, dry_run: bool, thread_pool_size: int, secret_reader: SecretReaderBase
    ) -> None:
        super().__init__(
            dry_run=dry_run,
            thread_pool_size=thread_pool_size,
            marker=LOGMARKER,
            scope="imagemanifestvuln",
            secret_reader=secret_reader,
        )
        self.settings = queries.get_app_interface_settings()

    def _post(self, manifest: dict[Any, Any]) -> Optional[requests.Response]:
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
    def _get_imagemanifestvuln(
        cluster: str, oc_map: OC_Map
    ) -> Optional[dict[str, Any]]:
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

    def run(self) -> None:
        clusters: list[ClusterV1] = get_clusters()
        oc_map_parameters = get_oc_connection_parameters_from_clusters(
            secret_reader=self.secret_reader, clusters=clusters
        )
        oc_map = OCMap(
            connection_parameters=oc_map_parameters,
            clusters_untyped=[cluster.dict(by_alias=True) for cluster in clusters],
            integration=QONTRACT_INTEGRATION,
            settings_untyped=self.settings,
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


def run(dry_run: bool = False, thread_pool_size: int = 10) -> None:
    vault_settings = get_app_interface_vault_settings()
    if not vault_settings:
        raise Exception("Missing app-interface vault_settings")
    secret_reader = create_secret_reader(use_vault=vault_settings.vault)
    dashdotdb_cso = DashdotdbCSO(
        dry_run=dry_run, thread_pool_size=thread_pool_size, secret_reader=secret_reader
    )
    dashdotdb_cso.run()
