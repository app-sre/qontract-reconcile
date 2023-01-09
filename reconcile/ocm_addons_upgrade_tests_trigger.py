import logging
from typing import Optional

from reconcile import queries
from reconcile.utils.jenkins_api import JenkinsApi
from reconcile.utils.ocm import OCMMap
from reconcile.utils.secret_reader import SecretReader
from reconcile.utils.state import State

QONTRACT_INTEGRATION = "ocm-addons-upgrade-tests-trigger"


def run(dry_run: bool) -> None:
    settings = queries.get_app_interface_settings()
    secret_reader = SecretReader(queries.get_secret_reader_settings())
    accounts = queries.get_state_aws_accounts()
    state = State(
        integration=QONTRACT_INTEGRATION, accounts=accounts, settings=settings
    )
    ocms = queries.get_openshift_cluster_managers()
    for ocm_info in ocms:
        ocm_name = ocm_info["name"]
        addon_upgrade_tests = ocm_info.get("addonUpgradeTests")
        if not addon_upgrade_tests:
            continue

        ocm_map = OCMMap(
            ocms=[ocm_info],
            integration=QONTRACT_INTEGRATION,
            settings=settings,
            init_addons=True,
        )

        ocm = ocm_map[ocm_name]
        state_updates: dict[str, Optional[str]] = {}
        for aut in addon_upgrade_tests:
            addon_name = aut["addon"]["name"]
            addon_org_version = None
            should_trigger = True
            state_key = f"{ocm_name}/{addon_name}"
            last_known_version = state.get(state_key, None)

            for cluster in ocm.clusters:
                if not should_trigger:
                    break
                cluster_addons = ocm.get_cluster_addons(cluster, with_version=True)
                for ca in cluster_addons:
                    if ca["id"] != addon_name:
                        continue
                    ca_version = ca["version"]
                    # all clusters should be in the same version to trigger a job
                    # store the version in addon_org_version
                    if not addon_org_version:
                        addon_org_version = ca_version
                    # is cluster addon version different from the rest of the clusters?
                    # this means that an upgrade is progressing through the clusters.
                    if addon_org_version != ca_version:
                        should_trigger = False
                        break
                    # is cluster addon version the same as the last known version?
                    # this means no upgrade has happened.
                    if ca_version == last_known_version:
                        should_trigger = False
                        break

            if should_trigger:
                # store state updates because the list of addons and jobs to trigger
                # may reference the same addon multiple times in order to trigger
                # multiple jobs. update the state only when we are done with this org.
                state_updates[addon_name] = addon_org_version
                # now trigger the job already, people are waiting!
                instance = aut["instance"]
                job_name = aut["name"]
                logging.info(
                    [
                        "trigger_job",
                        instance["name"],
                        job_name,
                        addon_name,
                        addon_org_version,
                    ]
                )
                if not dry_run:
                    jenkins = JenkinsApi.init_jenkins_from_secret(
                        secret_reader, instance["token"], ssl_verify=False
                    )
                    jenkins.trigger_job(job_name)

        if not dry_run:
            for addon_name, addon_version in state_updates.items():
                state_key = f"{ocm_name}/{addon_name}"
                state.add(state_key, addon_version, force=True)
