import enum
import logging
from typing import (
    Optional,
    cast,
)

from reconcile.gql_definitions.common.app_interface_dms_settings import (
    DeadMansSnitchSettingsV1,
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


class Action(enum.Enum):
    create_snitch = "create_snitch_url"
    delete_snitch = "delete_snitch_url"
    update_vault = "update_vault_data"

class DiffData:
    """Class to store the reconcile activity on current state derived from desired state """
    def __init__(self, cluster_name: str, action: Action, data: Optional[str] = None) -> None:
        self.cluster_name = cluster_name
        self.action = action
        if data:
            self.data = data

class DiffHandler:
    """ Handler class which to create/delete/update vault based on action on DiffData"""
    def __init__(self, deadmanssnitch_api: DeadMansSnitchApi, settings: DeadMansSnitchSettingsV1, vault_client: _VaultClient) -> None:
        self.deadmanssnitch_api = deadmanssnitch_api
        self.settings = settings
        self.vault_client = vault_client

    def summarize(self, diffs: list[DiffData]) -> str:
        return "\n".join(
            f"cluster name: {diff.cluster_name} - action: {diff.action.value}"
            for diff in diffs
        )

    def apply_diff(self, diff: DiffData) -> None:
        match diff.action:
            case Action.create_snitch:
                self.create_snitch(diff.cluster_name)
            case Action.delete_snitch:
                self.deadmanssnitch_api.delete_snitch(diff.data)
            case Action.update_vault:
                self.vault_client.write({"path": f"{self.settings.snitches_path}/deadmanssnitch-{diff.cluster_name}-url", "data": diff.data})


    def create_snitch(self, cluster_name: str) -> None:
        tags = ["app-sre"]
        alert_email = [self.settings.alert_email]
        payload = {
            "name": f"prometheus.{cluster_name}.devshift.net",
            "alert_type": "Heartbeat",
            "interval": "15_minute",
            "tags": tags,
            "alert_email": alert_email,
            "notes": self.settings.notes_link,
        }

        snitch = self.deadmanssnitch_api.create_snitch(payload=payload)
        self.vault_client.write({"path": f"{self.settings.snitches_path}/deadmanssnitch-{cluster_name}-url", "data": snitch.check_in_url})

class DeadMansSnitchIntegration(QontractReconcileIntegration[NoParams]):
    """ Integration to automate deadmanssnitch snitch api during cluster dressup."""
    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    def __init__(self) -> None:
        super().__init__(NoParams())
        self.qontract_integration_version = make_semver(0, 1, 0)

    def add_vault_data(self, snitch: Snitch, snitch_secret_path: str) -> Snitch:
        try:
            full_secret_path = {"path": snitch_secret_path, "field": f"deadmanssnitch-{snitch.get_cluster_name()}-url"}
            snitch.vault_data = self.secret_reader.read(full_secret_path).strip()
        except SecretNotFound:
            snitch.vault_data = SECRET_NOT_FOUND
        return snitch



    def get_current_state(self, deadmanssnitch_api: DeadMansSnitchApi, clusters: list[ClusterV1], snitch_secret_path: str) -> dict[str, Snitch]:
        # current state includes for deadmanssnithch response and associated secret in vault
        snitches = deadmanssnitch_api.get_snitches(tags=["app-sre"])
        # create snitch_map only for  the desired clusters
        snitches_with_cluster_mapping = {snitch.get_cluster_name(): snitch for snitch in snitches}
        current_state = {cluster.name: self.add_vault_data(snitch, snitch_secret_path)
                        for cluster in clusters
                        if (snitch := snitches_with_cluster_mapping.get(cluster.name))}
        return current_state

    @staticmethod
    def get_diff(current_state: dict[str, Snitch], desired_state: list[ClusterV1]) -> list[DiffData]:
        # get all the clusters which have `enableDeadMansSnitch: True`
        desired_cluster_enabled_true = [cluster.name for cluster in desired_state if cluster.enable_dead_mans_snitch]
        # get all the clusters which have `enableDeadMansSnitch: False`
        desired_cluster_enabled_false = [cluster.name for cluster in desired_state if not cluster.enable_dead_mans_snitch]
        create_snitches = [
            DiffData(cluster_name=cluster,
                     action=Action.create_snitch)
                     # add cluster to create set only in case they do not exist in current state
                     for cluster in desired_cluster_enabled_true - current_state.keys()
        ]
        delete_snitches = [
            DiffData(cluster_name=cluster,
                     action=Action.delete_snitch,
                     data=current_state[cluster].token)
                     # add to delete set only if they exists in current state and flag is set to false
                     for cluster in desired_cluster_enabled_false & current_state.keys()
        ]
        update_vault = [
            DiffData(cluster_name=cluster,
                     action=Action.update_vault,
                     data=current_state[cluster].check_in_url)
                     for cluster in desired_cluster_enabled_true & current_state.keys()
                     # add to update set only if they exists, flag is set to true but vault and snitch url mismatch
                     if current_state[cluster].vault_data and current_state[cluster].vault_data != current_state[cluster].check_in_url
        ]
        return create_snitches + delete_snitches + update_vault




    def apply_diffs(self, dry_run: bool, diffs: list[DiffData], diff_handler: DiffHandler) -> None:
        if len(diffs) == 0:
            return
        logging.info(diff_handler.summarize(diffs=diffs))
        if dry_run:
            return
        for diff in diffs:
            try:
                diff_handler.apply_diff(diff)
            except Exception as e:
                logging.error(str(e))
                continue



    def run(self, dry_run: bool) -> None:
        # Initialize deadmanssnitch_api
        settings = get_deadmanssnitch_settings()
        token = self.secret_reader.read({"path": settings.token_creds.path, "field": settings.token_creds.field})
        deadmanssnitch_api = DeadMansSnitchApi(token=token)
        vault_client = cast(_VaultClient, VaultClient())
        diff_handler = DiffHandler(deadmanssnitch_api, settings, vault_client)
        # desired state - filter cluster having enableDeadMansSnitch field
        clusters = [cluster for cluster in get_clusters_with_dms() if cluster.enable_dead_mans_snitch is not None]
        # current state - get snitches for tag app-sre
        current_state = self.get_current_state(deadmanssnitch_api, clusters, settings.snitches_path)
        if len(current_state) > 0 and len(clusters) > 0:
            diff = self.get_diff(current_state=current_state, desired_state=clusters)
            self.apply_diffs(dry_run, diff, diff_handler)
        # close session
        deadmanssnitch_api.close_session()


