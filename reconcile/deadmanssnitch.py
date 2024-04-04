import logging
from typing import (
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
from reconcile.utils.semver_helper import make_semver
from reconcile.utils.vault import (
    VaultClient,
    _VaultClient,
)

QONTRACT_INTEGRATION = "deadmanssnitch"
SECRET_NOT_FOUND = "SECRET_NOT_FOUND"


class SnitchSpec(BaseModel):
    """Class to hold values from cluster file and settings"""

    name: str
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

    @staticmethod
    def get_snitch_name(cluster: ClusterV1) -> str:
        return cluster.prometheus_url.replace("https://", "")

    @staticmethod
    def get_vault_key(cluster_name: str) -> str:
        return f"deadmanssnitch-{cluster_name}-url"

    def add_vault_data(
        self, cluster_name: str, snitch: Snitch, vault_snitch_map: dict[str, str]
    ) -> Snitch:
        if snitch_url := vault_snitch_map.get(self.get_vault_key(cluster_name)):
            snitch.vault_data = snitch_url
        else:
            snitch.vault_data = SECRET_NOT_FOUND
        return snitch

    def create_snitch(
        self,
        snitch_spec: SnitchSpec,
        deadmanssnitch_api: DeadMansSnitchApi,
    ) -> Snitch:
        payload = {
            "name": snitch_spec.name,
            "alert_type": snitch_spec.alert_type,
            "interval": snitch_spec.interval,
            "tags": snitch_spec.tags,
            "alert_email": snitch_spec.alert_email,
            "notes": snitch_spec.notes,
        }
        snitch_data = deadmanssnitch_api.create_snitch(payload=payload)
        return snitch_data

    def reconcile(
        self,
        dry_run: bool,
        current_state: dict[str, Snitch],
        desired_state: dict[str, SnitchSpec],
        deadmanssnitch_api: DeadMansSnitchApi,
        vault_snitch_map: dict[str, str],
    ) -> None:
        diffs = diff_mappings(
            current=current_state,
            desired=desired_state,
            equal=lambda current, desired: current.name == desired.name,
        )
        errors = []
        vault_snitch_map_copy = vault_snitch_map.copy()
        for cluster_name, snitch in diffs.add.items():
            logging.info("[cluster_name:%s] [Action:create_snitch]", cluster_name)
            if not dry_run:
                try:
                    snitch_data = self.create_snitch(snitch, deadmanssnitch_api)
                    vault_snitch_map_copy[self.get_vault_key(cluster_name)] = (
                        snitch_data.check_in_url
                    )
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
                logging.info("[cluster_name:%s] [Action:update_vault]", cluster_name)
                vault_snitch_map_copy[self.get_vault_key(cluster_name)] = (
                    diff_pair.current.check_in_url
                )

        # write to vault in case there is change in secret i.e in case of creation/update
        if vault_snitch_map != vault_snitch_map_copy and not dry_run:
            try:
                self.vault_client.write(
                    {
                        "path": self.settings.snitches_path,
                        "data": vault_snitch_map_copy,
                    },
                    decode_base64=False,
                )
            except Exception as e:
                errors.append(e)

        if errors:
            raise ExceptionGroup("Errors occurred while reconcile", errors)

    def get_current_state(
        self,
        deadmanssnitch_api: DeadMansSnitchApi,
        clusters: list[ClusterV1],
        vault_snitch_map: dict[str, str],
    ) -> dict[str, Snitch]:
        snitch_name_to_cluster_name_mapping = {
            self.get_snitch_name(cluster): cluster.name for cluster in clusters
        }
        # current state includes for deadmanssnithch response and associated secret in vault
        snitches = deadmanssnitch_api.get_snitches(tags=self.settings.tags)
        # create snitch_map only for  the desired clusters
        current_state = {
            cluster_name: self.add_vault_data(cluster_name, snitch, vault_snitch_map)
            for snitch in snitches
            if (cluster_name := snitch_name_to_cluster_name_mapping.get(snitch.name))
        }
        return current_state

    def get_desired_state(
        self,
        clusters: list[ClusterV1],
    ) -> dict[str, SnitchSpec]:
        desired_state = {
            cluster.name: SnitchSpec(
                name=self.get_snitch_name(cluster),
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
        # get all snitch secrets from vault
        vault_snitch_map = self.secret_reader.read_all({
            "path": self.settings.snitches_path
        })
        with DeadMansSnitchApi(token=token) as deadmanssnitch_api:
            # desired state - get the  clusters having enableDeadMansSnitch field
            clusters = get_clusters_with_dms()
            desired_state = self.get_desired_state(clusters)
            # create current state from deadmanssnitch and vault
            current_state = self.get_current_state(
                deadmanssnitch_api,
                clusters,
                vault_snitch_map,
            )
            self.reconcile(
                dry_run,
                current_state=current_state,
                desired_state=desired_state,
                deadmanssnitch_api=deadmanssnitch_api,
                vault_snitch_map=vault_snitch_map,
            )
