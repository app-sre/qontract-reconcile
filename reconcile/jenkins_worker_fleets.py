import logging
from typing import (
    Any,
    cast,
)

from reconcile import queries
from reconcile.jenkins.types import JenkinsWorkerFleet
from reconcile.utils.external_resources import get_external_resource_specs
from reconcile.utils.jenkins_api import JenkinsApi
from reconcile.utils.secret_reader import SecretReader
from reconcile.utils.terrascript_aws_client import TerrascriptClient as Terrascript

QONTRACT_INTEGRATION = "jenkins-worker-fleets"


def get_current_state(jenkins: JenkinsApi) -> list[JenkinsWorkerFleet]:
    current_state = []

    jenkins_config = cast(dict[str, Any], jenkins.get_jcasc_config().get("jenkins"))
    clouds = cast(list[dict[str, Any]], jenkins_config.get("clouds", []))
    for c in clouds:
        # eC2Fleet is defined by jcasc schema
        fleet = c.get("eC2Fleet", None)
        if fleet:
            current_state.append(JenkinsWorkerFleet(**fleet))

    # fix https://github.com/jenkinsci/ec2-fleet-plugin/issues/323
    config = {"jenkins": {"clouds": clouds}}
    jenkins.apply_jcasc_config(config)

    return current_state


def get_desired_state(
    terrascript: Terrascript, workerFleets: list[dict[str, Any]]
) -> list[JenkinsWorkerFleet]:
    desired_state = []

    for f in workerFleets:
        namespace = f["namespace"]
        account = f["account"]
        identifier = f["identifier"]
        specs = get_external_resource_specs(namespace)
        found = False
        for spec in specs:
            if spec.provider != "asg":
                continue
            if (spec.provisioner_name, spec.identifier) == (account, identifier):
                found = True
                values = terrascript.init_values(spec, init_tags=False)
                region = (
                    values.get("region") or spec.provisioner["resourcesDefaultRegion"]
                )
                f["name"] = identifier
                f["fleet"] = identifier
                f["region"] = region
                f["minSize"] = values.get("min_size")
                f["maxSize"] = values.get("max_size")
                f["computerConnector"] = {
                    "sSHConnector": {"credentialsId": f["credentialsId"]}
                }
                f = dict((k, v) for k, v in f.items() if v is not None)
                desired_state.append(JenkinsWorkerFleet(**f))
                break
        if not found:
            raise ValueError(
                f"Could not find asg identifier {identifier} "
                f'for account {account} in namespace {namespace["name"]}'
            )
    return desired_state


def act(
    dry_run: bool,
    instance_name: str,
    current_state: list[JenkinsWorkerFleet],
    desired_state: list[JenkinsWorkerFleet],
    jenkins: JenkinsApi,
) -> None:
    to_add = set(desired_state) - set(current_state)
    to_delete = set(current_state) - set(desired_state)
    to_compare = set(current_state) & set(desired_state)

    to_update = []
    for f in to_compare:
        current_fleet = current_state[current_state.index(f)]
        desired_fleet = desired_state[desired_state.index(f)]
        if current_fleet.differ(desired_fleet):
            logging.debug("CURRENT: " + str(current_fleet.dict(by_alias=True)))
            logging.debug("DESIRED: " + str(desired_fleet.dict(by_alias=True)))
            to_update.append(desired_fleet)

    if to_add or to_delete or to_update:
        for fleet in to_add:
            logging.info(["create_jenkins_worker_fleet", instance_name, fleet.name])
        for fleet in to_delete:
            logging.info(["delete_jenkins_worker_fleet", instance_name, fleet.name])
        for fleet in to_update:
            logging.info(["update_jenkins_worker_fleet", instance_name, fleet.name])

        if not dry_run:
            d_clouds = []
            for d in desired_state:
                d_clouds.append({"eC2Fleet": d.dict(by_alias=True)})
            config = {"jenkins": {"clouds": d_clouds}}
            jenkins.apply_jcasc_config(config)


def run(dry_run: bool) -> None:
    jenkins_instances = queries.get_jenkins_instances(worker_fleets=True)
    settings = queries.get_app_interface_settings()
    secret_reader = SecretReader(settings)

    # initiating terrascript with an empty list of accounts,
    # as we are not really initiating terraform configuration
    # but only using inner functions.
    terrascript = Terrascript(
        QONTRACT_INTEGRATION,
        "",
        1,
        accounts=[],
        settings=settings,
        prefetch_resources_by_schemas=["/aws/asg-defaults-1.yml"],
    )

    for instance in jenkins_instances:
        workerFleets = instance.get("workerFleets", [])
        if not workerFleets:
            # Skip instance if no fleets defined
            continue

        token = instance["token"]
        instance_name = instance["name"]
        jenkins = JenkinsApi.init_jenkins_from_secret(secret_reader, token)
        current_state = get_current_state(jenkins)
        desired_state = get_desired_state(terrascript, workerFleets)
        act(dry_run, instance_name, current_state, desired_state, jenkins)


def early_exit_desired_state(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return {
        "jenkins_instances": queries.get_jenkins_instances(worker_fleets=True),
    }
