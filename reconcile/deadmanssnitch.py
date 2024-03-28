import logging
from typing import (
    Optional,
    cast,
)

from reconcile.gql_definitions.common.clusters_with_dms import ClusterV1
from reconcile.typed_queries.app_interface_deadmanssnitch_settings import (
    get_deadmanssnitch_settings,
)
from reconcile.typed_queries.clusters_with_dms import get_clusters_with_dms
from reconcile.utils.deadmanssnitch_api import (
    DeadMansSnitchApi,
    Snitch,
)
from reconcile.utils.runtime.integration import (
    NoParams,
    QontractReconcileIntegration,
)
from reconcile.utils.secret_reader import (
    SecretNotFound,
)
from reconcile.utils.semver_helper import make_semver
from reconcile.utils.vault import (
    VaultClient,
    _VaultClient,
)

QONTRACT_INTEGRATION = "deadmanssnitch"
SECRET_NOT_FOUND = "SECRET_NOT_FOUND"


class DeadMansSnitchIntegration(QontractReconcileIntegration[NoParams]):
    """Integration to automate deadmanssnitch snitch api during cluster dressup."""

    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    def __init__(self) -> None:
        super().__init__(NoParams())
        self.qontract_integration_version = make_semver(0, 1, 0)
        self.settings = get_deadmanssnitch_settings()
        self.vault_client = cast(_VaultClient, VaultClient())

    def write_snitch_to_vault(self, cluster_name: str, snitch_url: str) -> None:
        self.vault_client.write(
            {
                "path": self.settings.snitches_path,
                "data": {f"deadmanssnitch-{cluster_name}-url": snitch_url},
            },
            decode_base64=False,
        )

    def add_vault_data(
        self, cluster_name: str, snitch: Snitch, snitch_secret_path: str
    ) -> Snitch:
        try:
            full_secret_path = {
                "path": snitch_secret_path,
                "field": f"deadmanssnitch-{cluster_name}-url",
            }
            snitch.vault_data = self.secret_reader.read(full_secret_path).strip()
        except SecretNotFound:
            snitch.vault_data = SECRET_NOT_FOUND
        return snitch

    def get_current_state(
        self,
        deadmanssnitch_api: DeadMansSnitchApi,
        clusters: list[ClusterV1],
        snitch_secret_path: str,
        cluster_to_prometheus_mapping: dict[str, str],
    ) -> dict[str, Snitch]:
        # current state includes for deadmanssnithch response and associated secret in vault
        snitches = deadmanssnitch_api.get_snitches(tags=["app-sre"])
        # create snitch_map only for  the desired clusters
        snitches_with_cluster_mapping = {
            cluster.name: snitch
            for snitch in snitches
            for cluster in clusters
            if (cluster_to_prometheus_mapping.get(cluster.name) == snitch.name)
        }
        current_state = {
            cluster.name: self.add_vault_data(cluster.name, snitch, snitch_secret_path)
            for cluster in clusters
            if (snitch := snitches_with_cluster_mapping.get(cluster.name))
        }
        return current_state

    def create_snitch(
        self,
        cluster: ClusterV1,
        deadmanssnitch_api: DeadMansSnitchApi,
        cluster_prom_mapping: dict[str, str],
    ) -> None:
        alert_email = [self.settings.alert_email]
        payload = {
            "name": cluster_prom_mapping.get(cluster.name),
            "alert_type": self.settings.alert_type,
            "interval": self.settings.interval,
            "tags": self.settings.tags,
            "alert_email": alert_email,
            "notes": self.settings.notes_link,
        }
        snitch = deadmanssnitch_api.create_snitch(payload=payload)
        self.write_snitch_to_vault(
            cluster_name=cluster.name, snitch_url=snitch.check_in_url
        )

    def reconcile(
        self,
        dry_run: bool,
        deadmanssnitch_api: DeadMansSnitchApi,
        cluster: ClusterV1,
        cluster_to_prometheus_mapping: dict[str, str],
        snitch: Optional[Snitch] = None,
    ) -> None:
        if cluster.enable_dead_mans_snitch and snitch is None:
            # if cluster's enable_dead_mans_snitch is set to True and it is not present in current state, create snitch
            logging.info("[cluster_name:%s] [Action:create_snitch]", cluster.name)
            if not dry_run:
                self.create_snitch(
                    cluster, deadmanssnitch_api, cluster_to_prometheus_mapping
                )
        if not cluster.enable_dead_mans_snitch and snitch:
            # if cluster's enable_dead_mans_snitch is set to False and it is present in current state, delete snitch
            logging.info("[cluster_name:%s] [Action:delete_snitch_url]", cluster.name)
            if not dry_run:
                deadmanssnitch_api.delete_snitch(snitch.token)
        if cluster.enable_dead_mans_snitch and snitch:
            # if cluster's enable_dead_mans_snitch is set to True and it is present in current state,update vault only if
            # vault url and check_in_url is different
            if snitch.needs_vault_update():
                logging.info(
                    "[cluster_name:%s] [Action:update_vault_value]", cluster.name
                )
                if not dry_run:
                    self.write_snitch_to_vault(
                        cluster_name=cluster.name, snitch_url=snitch.check_in_url
                    )

    def run(self, dry_run: bool) -> None:
        # Initialize deadmanssnitch_api
        token = self.secret_reader.read({
            "path": self.settings.token_creds.path,
            "field": self.settings.token_creds.field,
        })
        with DeadMansSnitchApi(token=token) as deadmanssnitch_api:
            # desired state - get the  clusters having enableDeadMansSnitch field
            clusters = get_clusters_with_dms()
            # create a mapping between prometheus url without the https:// and cluster name
            cluster_to_prometheus_mapping = {
                cluster.name: cluster.prometheus_url.replace("https://", "")
                for cluster in clusters
            }
            current_state = self.get_current_state(
                deadmanssnitch_api,
                clusters,
                self.settings.snitches_path,
                cluster_to_prometheus_mapping,
            )

            errors = []
            # for each cluster reconcile against the current_state of it.
            for cluster in clusters:
                try:
                    self.reconcile(
                        dry_run,
                        deadmanssnitch_api,
                        cluster,
                        snitch=current_state.get(cluster.name),
                        cluster_to_prometheus_mapping=cluster_to_prometheus_mapping,
                    )
                except Exception as e:
                    errors.append(e)
            if errors:
                raise ExceptionGroup("Errors occurred while reconcile", errors)
