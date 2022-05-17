import logging

from datetime import datetime
from urllib.parse import urlparse
from sretoolbox.utils import retry
from github.GithubException import UnknownObjectException

from reconcile.slack_base import slackapi_from_permissions
from reconcile.utils.github_api import GithubApi
from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.pagerduty_api import PagerDutyMap
from reconcile.utils.repo_owners import RepoOwners
from reconcile.utils.slack_api import SlackApiError
from reconcile import queries


DATE_FORMAT = "%Y-%m-%d %H:%M"
QONTRACT_INTEGRATION = "slack-usergroups"


class GitApi:
    def __new__(cls, url: str, *args, **kwargs):
        parsed_url = urlparse(url)
        settings = queries.get_app_interface_settings()

        if parsed_url.hostname:
            if "github" in parsed_url.hostname:
                instance = queries.get_github_instance()
                return GithubApi(instance, repo_url=url, settings=settings)
            if "gitlab" in parsed_url.hostname:
                instance = queries.get_gitlab_instance()
                return GitLabApi(instance, project_url=url, settings=settings)

        raise ValueError(f"Unable to handle URL: {url}")


def get_slack_map():
    settings = queries.get_app_interface_settings()
    permissions = queries.get_permissions_for_slack_usergroup()
    slack_map = {}
    for sp in permissions:
        workspace = sp["workspace"]
        workspace_name = workspace["name"]
        if workspace_name in slack_map:
            continue

        workspace_spec = {
            "slack": slackapi_from_permissions(sp, settings),
            "managed_usergroups": workspace["managedUsergroups"],
        }
        slack_map[workspace_name] = workspace_spec
    return slack_map


def get_pagerduty_map():
    instances = queries.get_pagerduty_instances()
    settings = queries.get_app_interface_settings()
    return PagerDutyMap(instances, settings)


def get_current_state(slack_map):
    """
    Get the current state of Slack usergroups.

    :param slack_map: Slack data from app-interface
    :type slack_map: dict

    :return: current state data, keys are workspace -> usergroup
                (ex. state['coreos']['app-sre-ic']
    :rtype: dict
    """
    current_state = {}

    for workspace, spec in slack_map.items():
        slack = spec["slack"]
        managed_usergroups = spec["managed_usergroups"]
        for ug in managed_usergroups:
            users, channels, description = slack.describe_usergroup(ug)
            current_state.setdefault(workspace, {})[ug] = {
                "workspace": workspace,
                "usergroup": ug,
                "users": users,
                "channels": channels,
                "description": description,
            }

    return current_state


def get_slack_username(user):
    return user["slack_username"] or user["org_username"]


def get_pagerduty_name(user):
    return user["pagerduty_username"] or user["org_username"]


@retry()
def get_slack_usernames_from_pagerduty(pagerduties, users, usergroup, pagerduty_map):
    all_slack_usernames = []
    all_pagerduty_names = [get_pagerduty_name(u) for u in users]
    for pagerduty in pagerduties or []:
        pd_schedule_id = pagerduty["scheduleID"]
        if pd_schedule_id is not None:
            pd_resource_type = "schedule"
            pd_resource_id = pd_schedule_id
        pd_escalation_policy_id = pagerduty["escalationPolicyID"]
        if pd_escalation_policy_id is not None:
            pd_resource_type = "escalationPolicy"
            pd_resource_id = pd_escalation_policy_id

        pd = pagerduty_map.get(pagerduty["instance"]["name"])
        pagerduty_names = pd.get_pagerduty_users(pd_resource_type, pd_resource_id)
        if not pagerduty_names:
            continue
        pagerduty_names = [
            name.split("+", 1)[0] for name in pagerduty_names if "nobody" not in name
        ]
        if not pagerduty_names:
            continue
        slack_usernames = [
            get_slack_username(u)
            for u in users
            if get_pagerduty_name(u) in pagerduty_names
        ]
        not_found_pagerduty_names = [
            pagerduty_name
            for pagerduty_name in pagerduty_names
            if pagerduty_name not in all_pagerduty_names
        ]
        if not_found_pagerduty_names:
            msg = (
                "[{}] PagerDuty username not found in app-interface: {} "
                "(hint: user files should contain "
                "pagerduty_username if it is different than org_username)"
            ).format(usergroup, not_found_pagerduty_names)
            logging.warning(msg)
        all_slack_usernames.extend(slack_usernames)

    return all_slack_usernames


@retry()
def get_slack_usernames_from_owners(owners_from_repo, users, usergroup):
    if owners_from_repo is None:
        return []

    all_slack_usernames = []

    for url_ref in owners_from_repo:
        # allow passing repo_url:ref to select different branch
        if url_ref.count(":") == 2:
            url, ref = url_ref.rsplit(":", 1)
        else:
            url = url_ref
            ref = "master"

        repo_cli = GitApi(url)

        if isinstance(repo_cli, GitLabApi):
            user_key = "org_username"
            missing_user_log_method = logging.warning
        elif isinstance(repo_cli, GithubApi):
            user_key = "github_username"
            missing_user_log_method = logging.debug
        else:
            raise TypeError(f"{type(repo_cli)} not supported")

        repo_owners = RepoOwners(git_cli=repo_cli, ref=ref)

        try:
            owners = repo_owners.get_root_owners()
        except UnknownObjectException:
            logging.error(f"ref {ref} not found for repo {url}")
            raise

        all_owners = owners["approvers"] + owners["reviewers"]

        if not all_owners:
            continue

        all_username_keys = [u[user_key] for u in users]

        slack_usernames = [
            get_slack_username(u)
            for u in users
            if u[user_key].lower() in [o.lower() for o in all_owners]
        ]
        not_found_users = [
            owner
            for owner in all_owners
            if owner.lower() not in [u.lower() for u in all_username_keys]
        ]
        if not_found_users:
            msg = (
                f"[{usergroup}] {user_key} not found in app-interface: "
                + f"{not_found_users}"
            )
            missing_user_log_method(msg)

        all_slack_usernames.extend(slack_usernames)

    return all_slack_usernames


def get_slack_usernames_from_schedule(schedule):
    if schedule is None:
        return []
    now = datetime.utcnow()
    all_slack_usernames = []
    for entry in schedule["schedule"]:
        start = datetime.strptime(entry["start"], DATE_FORMAT)
        end = datetime.strptime(entry["end"], DATE_FORMAT)
        if start <= now <= end:
            all_slack_usernames.extend(get_slack_username(u) for u in entry["users"])
    return all_slack_usernames


def get_desired_state(slack_map, pagerduty_map):
    """
    Get the desired state of Slack usergroups.

    :param slack_map: Slack data from app-interface
    :type slack_map: dict

    :param pagerduty_map: PagerDuty instance data
    :type pagerduty_map: reconcile.utils.pagerduty_api.PagerDutyMap

    :return: current state data, keys are workspace -> usergroup
                (ex. state['coreos']['app-sre-ic']
    :rtype: dict
    """
    permissions = queries.get_permissions_for_slack_usergroup()
    all_users = queries.get_users()

    desired_state = {}
    for p in permissions:
        if p["service"] != "slack-usergroup":
            continue
        skip_flag = p["skip"]
        if skip_flag:
            continue
        workspace = p["workspace"]
        managed_usergroups = workspace["managedUsergroups"]
        if managed_usergroups is None:
            continue

        workspace_name = workspace["name"]
        usergroup = p["handle"]
        description = p["description"]
        if usergroup not in managed_usergroups:
            raise KeyError(
                f"[{workspace_name}] usergroup {usergroup} \
                    not in managed usergroups {managed_usergroups}"
            )

        slack = slack_map[workspace_name]["slack"]
        ugid = slack.get_usergroup_id(usergroup)

        all_user_names = [get_slack_username(u) for r in p["roles"] for u in r["users"]]
        slack_usernames_pagerduty = get_slack_usernames_from_pagerduty(
            p["pagerduty"], all_users, usergroup, pagerduty_map
        )
        all_user_names.extend(slack_usernames_pagerduty)

        slack_usernames_repo = get_slack_usernames_from_owners(
            p["ownersFromRepos"], all_users, usergroup
        )
        all_user_names.extend(slack_usernames_repo)

        slack_usernames_schedule = get_slack_usernames_from_schedule(p["schedule"])
        all_user_names.extend(slack_usernames_schedule)

        user_names = list(set(all_user_names))
        users = slack.get_users_by_names(user_names)

        channel_names = [] if p["channels"] is None else p["channels"]
        channels = slack.get_channels_by_names(channel_names)

        try:
            desired_state[workspace_name][usergroup]["users"].update(users)
        except KeyError:
            desired_state.setdefault(workspace_name, {})[usergroup] = {
                "workspace": workspace_name,
                "usergroup": usergroup,
                "usergroup_id": ugid,
                "users": users,
                "channels": channels,
                "description": description,
            }
    return desired_state


def _update_usergroup_users_from_state(
    current_ug_state, desired_ug_state, slack_client, dry_run=True
):
    """
    Update the users in a Slack usergroup.

    :param current_ug_state: current state of usergroup
    :type current_ug_state: dict

    :param desired_ug_state: desired state of usergroup
    :type desired_ug_state: dict

    :param slack_client: client for calling Slack API
    :type slack_client: reconcile.utils.slack_api.SlackApi

    :param dry_run: whether to dryrun or not
    :type dry_run: bool

    :return: None
    """

    if current_ug_state.get("users") == desired_ug_state["users"]:
        logging.debug(
            "No usergroup user changes detected for %s", desired_ug_state["usergroup"]
        )
        return

    workspace = desired_ug_state["workspace"]
    usergroup = desired_ug_state["usergroup"]
    ugid = desired_ug_state["usergroup_id"]
    users = list(desired_ug_state["users"].keys())

    current_users = set(current_ug_state.get("users", {}).values())
    desired_users = set(desired_ug_state["users"].values())

    for user in desired_users - current_users:
        logging.info(["add_user_to_usergroup", workspace, usergroup, user])

    for user in current_users - desired_users:
        logging.info(["del_user_from_usergroup", workspace, usergroup, user])

    if not dry_run:
        try:
            slack_client.update_usergroup_users(ugid, users)
        except SlackApiError as error:
            # Prior to adding this, we weren't handling failed updates to user
            # groups. Now that we are, it seems like a good idea to start with
            # logging the errors and proceeding rather than blocking time
            # sensitive updates.
            logging.error(error)


def _update_usergroup_from_state(
    current_ug_state, desired_ug_state, slack_client, dry_run=True
):
    """
    Update a Slack usergroup.

    :param current_ug_state: current state of usergroup
    :type current_ug_state: dict

    :param desired_ug_state: desired state of usergroup
    :type desired_ug_state: dict

    :param slack_client: client for calling Slack API
    :type slack_client: reconcile.utils.slack_api.SlackApi

    :param dry_run: whether to dryrun or not
    :type dry_run: bool

    :return: None
    """

    channels_changed = current_ug_state.get("channels") != desired_ug_state["channels"]

    description_changed = (
        current_ug_state.get("description") != desired_ug_state["description"]
    )

    if not channels_changed and not description_changed:
        logging.debug(
            "No usergroup channel/description changes detected for %s",
            desired_ug_state["usergroup"],
        )
        return

    workspace = desired_ug_state["workspace"]
    usergroup = desired_ug_state["usergroup"]
    ugid = desired_ug_state["usergroup_id"]
    description = desired_ug_state["description"]
    channels = list(desired_ug_state["channels"].keys())

    current_channels = set(current_ug_state.get("channels", {}).values())
    desired_channels = set(desired_ug_state["channels"].values())

    for channel in desired_channels - current_channels:
        logging.info(["add_channel_to_usergroup", workspace, usergroup, channel])

    for channel in current_channels - desired_channels:
        logging.info(["del_channel_from_usergroup", workspace, usergroup, channel])

    if description_changed:
        logging.info(
            ["update_usergroup_description", workspace, usergroup, description]
        )

    if not dry_run:
        try:
            slack_client.update_usergroup(ugid, channels, description)
        except SlackApiError as error:
            logging.error(error)


def act(current_state, desired_state, slack_map, dry_run=True):
    """
    Reconcile the differences between the desired and current state for
    Slack usergroups.

    :param current_state: current Slack usergroup state
    :type current_state: dict

    :param desired_state: desired Slack usergroup state
    :type desired_state: dict

    :param slack_map: mapping of Slack workspace names to API clients
    :type slack_map: dict

    :param dry_run: indicates whether to run in dryrun mode or not
    :type dry_run: bool

    :return: None
    """
    for workspace, desired_ws_state in desired_state.items():
        for usergroup, desired_ug_state in desired_ws_state.items():
            current_ug_state = current_state.get(workspace, {}).get(usergroup, {})

            slack_client = slack_map[workspace]["slack"]

            _update_usergroup_users_from_state(
                current_ug_state, desired_ug_state, slack_client, dry_run=dry_run
            )

            _update_usergroup_from_state(
                current_ug_state, desired_ug_state, slack_client, dry_run=dry_run
            )


def run(dry_run):
    slack_map = get_slack_map()
    pagerduty_map = get_pagerduty_map()
    desired_state = get_desired_state(slack_map, pagerduty_map)
    current_state = get_current_state(slack_map)

    act(current_state, desired_state, slack_map, dry_run)
