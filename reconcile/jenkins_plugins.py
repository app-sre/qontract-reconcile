import logging
from collections.abc import Mapping
from typing import Any

from reconcile import queries
from reconcile.utils import gql
from reconcile.utils.jenkins_api import JenkinsApi
from reconcile.utils.secret_reader import SecretReader

INSTANCES_QUERY = """
{
  instances: jenkins_instances_v1 {
    name
    token {
      path
      field
      version
      format
    }
    plugins
  }
}
"""

QONTRACT_INTEGRATION = "jenkins-plugins"


def get_jenkins_map(
    plugins_only=False, desired_instances=None
) -> dict[str, JenkinsApi]:
    gqlapi = gql.get_api()
    jenkins_instances = gqlapi.query(INSTANCES_QUERY)["instances"]
    secret_reader = SecretReader(queries.get_secret_reader_settings())

    jenkins_map = {}
    for instance in jenkins_instances:
        instance_name = instance["name"]
        if desired_instances and instance_name not in desired_instances:
            continue
        if instance_name in jenkins_map:
            continue
        if plugins_only and not instance["plugins"]:
            continue

        token = instance["token"]
        jenkins = JenkinsApi.init_jenkins_from_secret(
            secret_reader, token, ssl_verify=False
        )
        jenkins_map[instance_name] = jenkins

    return jenkins_map


def get_current_state(jenkins_map: Mapping[str, JenkinsApi]) -> list[dict[str, Any]]:
    current_state = []

    for instance, jenkins in jenkins_map.items():
        plugins = jenkins.list_plugins()
        for plugin in plugins:
            current_state.append({"instance": instance, "plugin": plugin["shortName"]})

    return current_state


def get_desired_state():
    gqlapi = gql.get_api()
    jenkins_instances = gqlapi.query(INSTANCES_QUERY)["instances"]

    desired_state = []
    for instance in jenkins_instances:
        for plugin in instance["plugins"] or []:
            desired_state.append({"instance": instance["name"], "plugin": plugin})

    return desired_state


def calculate_diff(current_state, desired_state):
    diff = []
    plugins_to_install = subtract_states(desired_state, current_state, "install_plugin")
    diff.extend(plugins_to_install)

    return diff


def subtract_states(from_state, subtract_state, action):
    result = []

    for f_plugin in from_state:
        found = False
        for s_plugin in subtract_state:
            if f_plugin != s_plugin:
                continue
            found = True
            break
        if not found:
            result.append(
                {
                    "action": action,
                    "instance": f_plugin["instance"],
                    "plugin": f_plugin["plugin"],
                }
            )

    return result


def act(diff, jenkins_map):
    instance = diff["instance"]
    plugin = diff["plugin"]
    action = diff["action"]

    if action == "install_plugin":
        jenkins_map[instance].install_plugin(plugin)
    else:
        raise Exception("invalid action: {}".format(action))


def run(dry_run):
    jenkins_map = get_jenkins_map(plugins_only=True)
    current_state = get_current_state(jenkins_map)
    desired_state = get_desired_state()
    diffs = calculate_diff(current_state, desired_state)

    for diff in diffs:
        logging.info(list(diff.values()))

        if not dry_run:
            act(diff, jenkins_map)

    for instance in jenkins_map.values():
        instance.safe_restart()
