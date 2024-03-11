import logging
import sys
from typing import (
    Any,
    Optional,
    cast,
)

from reconcile.gql_definitions.common.app_interface_dms_settings import (
    DeadMansSnitchSettingsV1,
)
from reconcile.gql_definitions.common.clusters_with_dms import ClusterV1
from reconcile.status import ExitCodes
from reconcile.typed_queries.app_interface_deadmanssnitch_settings import (
    get_deadmanssnitch_settings,
)
from reconcile.typed_queries.clusters_with_dms import get_clusters_with_dms
from reconcile.utils.deadmanssnitch_api import DeadMansSnitchApi
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


class DiffHandler:
    UPDATE_VAULT = "update_vault"
    CREATE_SNITCH = "create_snitch"
    DELETE_SNITCH = "delete_snitch"

    def __init__(self, deadmanssnitch_api: DeadMansSnitchApi, settings: DeadMansSnitchSettingsV1, vault_client: VaultClient = None) -> None:
        self.deadmanssnitch_api = deadmanssnitch_api
        self.settings = settings
        if vault_client is not None:
            self.vault_client = vault_client
        else:
            self.vault_client = cast(_VaultClient, VaultClient())

    def create_diff_data(self, cluster_name: str, action: str, current_state: Optional[dict[str, Any]] = None) -> dict[str, str]:
        data: dict[str, str] = {}
        data["action"] = action
        data["cluster_name"] = cluster_name
        if action == self.UPDATE_VAULT:
            data["snitch_url"] = current_state["check_in_url"]
        elif action == self.DELETE_SNITCH:
            data["token"] = current_state["token"]
        return data

    def summarize(self, diffs: list[dict[str, str]]) -> str:
        summary: str = ""
        for diff in diffs:
            summary += f"cluster name: {diff['cluster_name']} - action: {diff['action']}\n"
        return summary

    def apply_diff(self, diff: dict[str, str]) -> None:
        match diff["action"]:
            case self.CREATE_SNITCH:
                self.create_snitch(diff)
            case self.DELETE_SNITCH:
                self.deadmanssnitch_api.delete_snitch(diff["token"])
            case self.UPDATE_VAULT:
                self.vault_client.write({"path": f"{self.settings.snitches_path}/deadmanssnitch-{diff['cluster_name']}-url", "data": diff['snitch_url']})


    def create_snitch(self, diff: dict[str, str]) -> None:
        tags = ["app-sre"]
        alert_email = [self.settings.alert_email]
        payload = {
            "name": f"prometheus.{diff['cluster_name']}.devshift.net",
            "alert_type": "Heartbeat",
            "interval": "15_minute",
            "tags": tags,
            "alert_email": alert_email,
            "notes": self.settings.notes_link,
        }
        try:
            snitch = self.deadmanssnitch_api.create_snitch(payload=payload)
            self.vault_client.write({"path": f"{self.settings.snitches_path}/deadmanssnitch-{diff['cluster_name']}-url", "data": snitch.check_in_url})
        except Exception as e:
            logging.error(str(e))
            return None


class DeadMansSnitchIntegration(QontractReconcileIntegration[NoParams]):
    """ Integration to automate deadmanssnitch snitch api during cluster dressup."""
    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    def __init__(self) -> None:
        super().__init__(NoParams())
        self.qontract_integration_version = make_semver(0, 1, 0)

    def get_current_state(self, deadmanssnitch_api: DeadMansSnitchApi, clusters: ClusterV1, snitch_secret_path: str) -> list[dict[str, Any]]:
        # current state includes for deadmanssnithch response and associated secret in vault
        current_state: list[dict[str, Any]] = []
        try:
            snitches = deadmanssnitch_api.get_snitches(tags=["app-sre"])
        except Exception as e:
            logging.error(str(e))
            return current_state
        # create snitch_map only for  the desired clusters
        for cluster in clusters:
            for snitch in snitches:
                if snitch.get_cluster_name() == cluster.name:
                    snitch_map = snitch.dict(by_alias=True)
                    snitch_map["cluster_name"] = cluster.name
                    try:
                        full_secret_path = {"path": snitch_secret_path, "field": f"deadmanssnitch-{snitch_map['cluster_name']}-url"}
                        # match the exact url value
                        snitch_map["vault_snitch_value"] = self.secret_reader.read(full_secret_path).strip()
                    except SecretNotFound:
                        # need to create a new vault secret for this record.
                        snitch_map["vault_snitch_value"] = SECRET_NOT_FOUND
                    except Exception as e:
                        logging.error(str(e))
                        continue
                    current_state.append(snitch_map)
        return current_state

    @staticmethod
    def get_diff(current_states: list[dict[str, Any]], desired_states: list[ClusterV1], diff_handler: DiffHandler) -> list[dict[str, str]]:
        diffs: list[dict[str, str]] = []
        for cluster in desired_states[:]:
            for current_state in current_states:
                if cluster.enable_dead_mans_snitch and cluster.name == current_state["cluster_name"]:
                    if current_state["check_in_url"] != current_state["vault_snitch_value"]:
                        # As snitch url is different in deadmanssnitch console and vault
                        # update the changes in vault
                        diffs.append(diff_handler.create_diff_data(action=DiffHandler.UPDATE_VAULT, cluster_name=cluster.name, current_state=current_state))
                    # remove the cluster from desired state since we  got a match on cluster name
                    desired_states.remove(cluster)
                if not cluster.enable_dead_mans_snitch and cluster.name == current_state["cluster_name"]:
                    # fire delete only in case, `enableDeadMansSnitch: False` and  it exists on deadmanssnitch
                    diffs.append(diff_handler.create_diff_data(action=DiffHandler.DELETE_SNITCH, cluster_name=current_state["cluster_name"], current_state=current_state))
                    desired_states.remove(cluster)
        for desired_state in desired_states:
            # we are left with only cluster which needs create_snitch if `enableDeadMansSnitch: True`
            if desired_state.enable_dead_mans_snitch:
                diffs.append(diff_handler.create_diff_data(action=DiffHandler.CREATE_SNITCH, cluster_name=desired_state.name))
        return diffs


    def apply_diffs(self, dry_run: bool, diffs: dict[str, Any], diff_handler: DiffHandler) -> None:
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
        settings: DeadMansSnitchSettingsV1 = None
        token: str = ""
        try:
            settings = get_deadmanssnitch_settings()
            token = self.secret_reader.read({"path": settings.token_creds.path, "field": settings.token_creds.field})
        except Exception as e:
            logging.error(str(e))
            sys.exit(ExitCodes.ERROR)
        deadmanssnitch_api = DeadMansSnitchApi(token=token)
        diff_handler = DiffHandler(deadmanssnitch_api, settings)
        # desired state - filter cluster having enableDeadMansSnitch field
        clusters = [cluster for cluster in get_clusters_with_dms() if cluster.enable_dead_mans_snitch is not None]
        # current state - get snitches for tag app-sre
        current_state = self.get_current_state(deadmanssnitch_api, clusters, settings.snitches_path)
        if len(current_state) > 0 and len(clusters) > 0:
            diff = self.get_diff(current_states=current_state, desired_states=clusters, diff_handler=diff_handler)
            self.apply_diffs(dry_run, diff, diff_handler)


