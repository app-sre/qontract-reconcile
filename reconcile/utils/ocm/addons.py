from typing import (
    Any,
    Optional,
)

from reconcile.utils.ocm.base import OCMAddonInstallation
from reconcile.utils.ocm_base_client import OCMBaseClient

ADDON_UPGRADE_POLICY_DESIRED_KEYS = {
    "id",
    "addon_id",
    "schedule_type",
    "schedule",
    "next_run",
    "version",
}


class AddonService:
    def get_addon_latest_versions(self, ocm_api: OCMBaseClient) -> dict[str, str]:
        """
        Returns the latest version for each addon.
        """
        latest_versions: dict[str, str] = {}
        for addon in ocm_api.get_paginated(f"{self.addon_base_api_path()}/addons"):
            addon_id = addon["id"]
            latest_versions[addon_id] = addon["version"]["id"]
        return latest_versions

    def get_addons_for_cluster(
        self,
        ocm_api: OCMBaseClient,
        cluster_id: str,
        addon_latest_versions: dict[str, str],
        required_state: Optional[str],
    ) -> list[OCMAddonInstallation]:
        """
        Returns a list of Addons installed on a cluster

        :param cluster_id: ID of the cluster
        :param addon_latest_versions: dict of addon_id -> latest version. This allows us to
            populate the addonsinstalation available upgrades in an efficient way.
        :param required_state: only return addons with this state
        """

        params: Optional[dict[str, Any]] = None
        if required_state:
            params = {"search": f"state='{required_state}'"}

        addons = []
        for addon in ocm_api.get_paginated(
            api_path=f"{self.addon_base_api_path()}/clusters/{cluster_id}/addons",
            params=params,
        ):
            current_version = addon["addon_version"]["id"]
            latest_version = addon_latest_versions.get(addon["id"])
            addon["addon_version"]["available_upgrades"] = (
                [latest_version] if latest_version != current_version else []
            )
            addons.append(OCMAddonInstallation(**addon))
        return addons

    def addon_base_api_path(self) -> str:
        raise NotImplementedError()

    def get_addon_upgrade_policies(
        self, ocm_api: OCMBaseClient, cluster_id: str, addon_id: Optional[str] = None
    ) -> list[dict[str, Any]]:
        raise NotImplementedError()

    def create_addon_upgrade_policy(
        self,
        ocm_api: OCMBaseClient,
        cluster_id: str,
        addon_id: str,
        schedule_type: str,
        version: str,
        next_run: str,
    ) -> None:
        raise NotImplementedError()

    def delete_addon_upgrade_policy(
        self, ocm_api: OCMBaseClient, cluster_id: str, policy_id: str
    ) -> None:
        raise NotImplementedError()


class AddonServiceV1(AddonService):
    """
    The original addon-service API that is part of CS.
    """

    def addon_base_api_path(self) -> str:
        return "/api/clusters_mgmt/v1"

    def get_addon_upgrade_policies(
        self, ocm_api: OCMBaseClient, cluster_id: str, addon_id: Optional[str] = None
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []

        for policy in ocm_api.get_paginated(
            f"{self.addon_base_api_path()}/clusters/{cluster_id}/addon_upgrade_policies"
        ):
            if addon_id and policy["addon_id"] != addon_id:
                continue
            policy_data = {
                k: v
                for k, v in policy.items()
                if k in ADDON_UPGRADE_POLICY_DESIRED_KEYS
            }
            policy_data["state"] = self._get_addon_upgrade_policy_state(
                ocm_api, cluster_id, policy["id"]
            )
            results.append(policy_data)

        return results

    def _get_addon_upgrade_policy_state(
        self, ocm_api: OCMBaseClient, cluster_id: str, addon_upgrade_policy_id: str
    ) -> Optional[str]:
        try:
            state_data = ocm_api.get(
                f"{self.addon_base_api_path()}/clusters/{cluster_id}/addon_upgrade_policies/{addon_upgrade_policy_id}/state"
            )
            return state_data.get("value")
        except Exception:
            return None

    def create_addon_upgrade_policy(
        self,
        ocm_api: OCMBaseClient,
        cluster_id: str,
        addon_id: str,
        schedule_type: str,
        version: str,
        next_run: str,
    ) -> None:
        """
        Creates a new Addon Upgrade Policy
        """
        spec = {
            "version": version,
            "schedule_type": schedule_type,
            "addon_id": addon_id,
            "cluster_id": cluster_id,
            "upgrade_type": "ADDON",
        }
        ocm_api.post(
            f"{self.addon_base_api_path()}/clusters/{cluster_id}/addon_upgrade_policies",
            spec,
        )

    def delete_addon_upgrade_policy(
        self, ocm_api: OCMBaseClient, cluster_id: str, policy_id: str
    ) -> None:
        """
        Deletes an existing Addon Upgrade Policy
        """
        ocm_api.delete(
            f"{self.addon_base_api_path()}/clusters/{cluster_id}/addon_upgrade_policies/{policy_id}"
        )


class AddonServiceV2(AddonService):
    """
    The dedicated addon-service API that is part of OCM.
    """

    def addon_base_api_path(self) -> str:
        return "/api/addons_mgmt/v1"

    def get_addon_upgrade_policies(
        self, ocm_api: OCMBaseClient, cluster_id: str, addon_id: Optional[str] = None
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []

        for policy in ocm_api.get_paginated(
            f"{self.addon_base_api_path()}/clusters/{cluster_id}/upgrade_plan"
        ):
            if addon_id and policy["addon_id"] != addon_id:
                continue
            policy_data = {
                k: v
                for k, v in policy.items()
                if k in ADDON_UPGRADE_POLICY_DESIRED_KEYS
            }
            results.append(policy_data)

        return results

    def create_addon_upgrade_policy(
        self,
        ocm_api: OCMBaseClient,
        cluster_id: str,
        addon_id: str,
        schedule_type: str,
        version: str,
        next_run: str,
    ) -> None:
        """
        Schedules an addon upgrade. Leverages addon-service upgrade plans behind the scene.
        """
        spec = {
            "version": version,
            "type": schedule_type,
            "addon_id": addon_id,
            "cluster_id": cluster_id,
            "next_run": next_run,
        }
        ocm_api.post(
            f"{self.addon_base_api_path()}/clusters/{cluster_id}/upgrade_plan", spec
        )

    def delete_addon_upgrade_policy(
        self, ocm_api: OCMBaseClient, cluster_id: str, policy_id: str
    ) -> None:
        """
        Deletes an existing upgrade plan.
        """
        ocm_api.delete(
            f"{self.addon_base_api_path()}/clusters/{cluster_id}/upgrade_plan/{policy_id}"
        )
