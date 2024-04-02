import logging
from typing import (
    Optional,
    cast,
)

from pydantic import BaseModel

from reconcile.gql_definitions.common.clusters_with_dms import ClusterV1
from reconcile.typed_queries.app_interface_deadmanssnitch_settings import (
    get_deadmanssnitch_settings,
)
from reconcile.typed_queries.clusters_with_dms import get_clusters_with_dms
from reconcile.utils.deadmanssnitch_api import (
    DeadMansSnitchApi,
    Snitch,
)
from reconcile.utils.differ import diff_mappings
from reconcile.utils.runtime.integration import (
    NoParams,
    QontractReconcileIntegration,
)
from reconcile.utils.secret_reader import (
    SecretNotFound,
)
from reconcile.utils.semver_helper import make_semver
from reconcile.utils.vault import (
    SecretFieldNotFound,
    VaultClient,
    _VaultClient,
)

QONTRACT_INTEGRATION = "deadmanssnitch"
SECRET_NOT_FOUND = "SECRET_NOT_FOUND"


class ClusterFields(BaseModel):
    """Class to hold values from cluster file and settings"""

    prometheus_url: str
    alert_email: list[str]
    alert_type: str
    interval: str
    tags: list[str]
    notes: str


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

    def write_snitch_to_vault(
        self, cluster_name: str, snitch_url: Optional[str]
    ) -> None:
        if snitch_url:
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
        except (SecretNotFound, SecretFieldNotFound):
            snitch.vault_data = SECRET_NOT_FOUND
        return snitch

    def create_snitch(
        self,
        cluster_name: str,
        cluster_fields: ClusterFields,
        deadmanssnitch_api: DeadMansSnitchApi,
    ) -> None:
        payload = {
            "name": cluster_fields.prometheus_url,
            "alert_type": cluster_fields.alert_type,
            "interval": cluster_fields.interval,
            "tags": cluster_fields.tags,
            "alert_email": cluster_fields.alert_email,
            "notes": cluster_fields.notes,
        }
        snitch_data = deadmanssnitch_api.create_snitch(payload=payload)
        self.write_snitch_to_vault(
            cluster_name=cluster_name, snitch_url=snitch_data.check_in_url
        )

    def reconcile(
        self,
        dry_run: bool,
        current_state: dict[str, Snitch],
        desired_state: dict[str, ClusterFields],
        deadmanssnitch_api: DeadMansSnitchApi,
    ) -> None:
        diffs = diff_mappings(
            current=current_state,
            desired=desired_state,
            equal=lambda current, desired: current.name == desired.prometheus_url,
        )
        errors = []
        for cluster_name, snitch in diffs.add.items():
            logging.info("[cluster_name:%s] [Action:create_snitch]", cluster_name)
            if not dry_run:
                try:
                    self.create_snitch(cluster_name, snitch, deadmanssnitch_api)
                except Exception as e:
                    errors.append(e)
        for cluster_name, snitch_value in diffs.delete.items():
            logging.info("[cluster_name:%s] [Action:delete_snitch]", cluster_name)
            if not dry_run:
                try:
                    deadmanssnitch_api.delete_snitch(snitch_value.token)
                except Exception as e:
                    errors.append(e)
        for cluster_name, diff_pair in diffs.identical.items():
            if diff_pair.current.needs_vault_update():
                logging.info(
                            "[cluster_name:%s] [Action:update_vault]", cluster_name
                        )
                if not dry_run:
                    try:
                        self.write_snitch_to_vault(
                            cluster_name=cluster_name,
                            snitch_url=diff_pair.current.check_in_url,
                        )
                    except Exception as e:
                        errors.append(e)
        if errors:
            raise ExceptionGroup("Errors occurred while reconcile", errors)

    def get_current_state(
        self,
        deadmanssnitch_api: DeadMansSnitchApi,
        clusters: list[ClusterV1],
        snitch_secret_path: str,
        cluster_to_prometheus_mapping: dict[str, str],
    ) -> dict[str, Snitch]:
        # current state includes for deadmanssnithch response and associated secret in vault
        snitches = deadmanssnitch_api.get_snitches(tags=self.settings.tags)
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

    def get_desired_state(
        self,
        clusters: list[ClusterV1],
        cluster_to_prometheus_mapping: dict[str, str],
    ) -> dict[str, ClusterFields]:
        desired_state = {
            cluster.name: ClusterFields(
                prometheus_url=cluster_to_prometheus_mapping.get(cluster.name),
                alert_email=self.settings.alert_mail_addresses,
                interval=self.settings.interval,
                tags=self.settings.tags,
                notes=self.settings.notes_link,
                alert_type=self.settings.alert_type,
            )
            for cluster in clusters
            if cluster.enable_dead_mans_snitch
        }
        return desired_state

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
            desired_state = self.get_desired_state(
                clusters, cluster_to_prometheus_mapping
            )
            current_state = self.get_current_state(
                deadmanssnitch_api,
                clusters,
                self.settings.snitches_path,
                cluster_to_prometheus_mapping,
            )
            self.reconcile(
                dry_run,
                current_state=current_state,
                desired_state=desired_state,
                deadmanssnitch_api=deadmanssnitch_api,
            )
