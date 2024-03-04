import logging
import sys
from collections.abc import (
    Callable,
    Iterable,
)
from datetime import datetime
from typing import (
    Any,
    Optional,
    Sequence,
    Union,
)
from urllib.parse import urlparse

from github.GithubException import UnknownObjectException
from pydantic import BaseModel
from pydantic.utils import deep_update
from sretoolbox.utils import retry

from reconcile import (
    openshift_users,
    queries,
)
from reconcile.gql_definitions.common.users import User
from reconcile.gql_definitions.slack_usergroups.clusters import ClusterV1
from reconcile.gql_definitions.slack_usergroups.clusters import query as clusters_query
from reconcile.gql_definitions.slack_usergroups.permissions import (
    PagerDutyTargetV1,
    PermissionSlackUsergroupV1,
    ScheduleEntryV1,
)
from reconcile.gql_definitions.slack_usergroups.permissions import (
    query as permissions_query,
)
from reconcile.gql_definitions.slack_usergroups.users import UserV1
from reconcile.gql_definitions.slack_usergroups.users import query as users_query
from reconcile.openshift_base import user_has_cluster_access
from reconcile.slack_base import get_slackapi
from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.typed_queries.pagerduty_instances import get_pagerduty_instances
from reconcile.utils import gql
from reconcile.utils.disabled_integrations import integration_is_enabled
from reconcile.utils.exceptions import (
    AppInterfaceSettingsError,
    UnknownError,
)
from reconcile.utils.github_api import GithubRepositoryApi
from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.pagerduty_api import (
    PagerDutyApiException,
    PagerDutyMap,
    get_pagerduty_map,
)
from reconcile.utils.repo_owners import RepoOwners
from reconcile.utils.secret_reader import (
    SecretReader,
    create_secret_reader,
)
from reconcile.utils.slack_api import (
    SlackApi,
    SlackApiError,
    UsergroupNotFoundException,
)

DATE_FORMAT = "%Y-%m-%d %H:%M"
QONTRACT_INTEGRATION = "slack-usergroups"
error_occurred = False


def get_git_api(url: str) -> Union[GithubRepositoryApi, GitLabApi]:
    """Return GitHub/GitLab API based on url."""
    parsed_url = urlparse(url)

    if parsed_url.hostname:
        if "github" in parsed_url.hostname:
            vault_settings = get_app_interface_vault_settings()
            secret_reader = create_secret_reader(use_vault=vault_settings.vault)
            instance = queries.get_github_instance()
            token = secret_reader.read(instance["token"])

            return GithubRepositoryApi(
                repo_url=url,
                token=token,
            )
        if "gitlab" in parsed_url.hostname:
            settings = queries.get_app_interface_settings()
            instance = queries.get_gitlab_instance()
            return GitLabApi(instance=instance, project_url=url, settings=settings)

    raise ValueError(f"Unable to handle URL: {url}")


class SlackObject(BaseModel):
    """Generic Slack object."""

    pk: str
    name: str

    def __hash__(self) -> int:
        return hash(self.pk)


class State(BaseModel):
    """State representation."""

    workspace: str = ""
    usergroup: str = ""
    description: str = ""
    users: set[SlackObject] = set()
    channels: set[SlackObject] = set()
    usergroup_id: Optional[str] = None

    def __bool__(self) -> bool:
        return self.workspace != ""  # noqa: PLC1901


SlackState = dict[str, dict[str, State]]


class WorkspaceSpec(BaseModel):
    """Slack workspace spec."""

    slack: SlackApi
    managed_usergroups: list[str] = []

    class Config:
        arbitrary_types_allowed = True


SlackMap = dict[str, WorkspaceSpec]


def compute_cluster_user_group(name: str) -> str:
    """Compute the cluster user group name."""
    return f"{name}-cluster"


def get_slack_map(
    secret_reader: SecretReader,
    permissions: Iterable[PermissionSlackUsergroupV1],
    desired_workspace_name: Optional[str] = None,
) -> SlackMap:
    """Return SlackMap (API) per workspaces."""
    slack_map = {}
    for sp in permissions:
        if desired_workspace_name and desired_workspace_name != sp.workspace.name:
            continue
        if sp.workspace.name in slack_map:
            continue

        token = None
        channel = None
        for int in sp.workspace.integrations or []:
            if int.name != QONTRACT_INTEGRATION:
                continue
            token = int.token
            channel = int.channel
        if not token or not channel:
            raise AppInterfaceSettingsError(
                f"Missing integration {QONTRACT_INTEGRATION} settings for "
                f"workspace {sp.workspace.name}"
            )
        slack_map[sp.workspace.name] = WorkspaceSpec(
            slack=get_slackapi(
                workspace_name=sp.workspace.name,
                token=secret_reader.read_secret(token),
                client_config=sp.workspace.api_client,
                channel=channel,
            ),
            managed_usergroups=sp.workspace.managed_usergroups,
        )
    return slack_map


def get_current_state(
    slack_map: SlackMap,
    desired_workspace_name: Optional[str],
    desired_usergroup_name: Optional[str],
    cluster_usergroups: list[str],
) -> SlackState:
    """
    Get the current state of Slack usergroups.

    :param slack_map: Slack data from app-interface
    :type slack_map: dict

    :return: current state data, keys are workspace -> usergroup
                (ex. state['coreos']['app-sre-ic']
    :rtype: dict
    """
    current_state: SlackState = {}

    for workspace, spec in slack_map.items():
        if desired_workspace_name and desired_workspace_name != workspace:
            continue

        for ug in spec.managed_usergroups + cluster_usergroups:
            if desired_usergroup_name and desired_usergroup_name != ug:
                continue
            try:
                users, channels, description = spec.slack.describe_usergroup(ug)
            except UsergroupNotFoundException:
                continue
            current_state.setdefault(workspace, {})[ug] = State(
                workspace=workspace,
                usergroup=ug,
                users={SlackObject(pk=pk, name=name) for pk, name in users.items()},
                channels={
                    SlackObject(pk=pk, name=name) for pk, name in channels.items()
                },
                description=description,
            )

    return current_state


def get_slack_username(user: User) -> str:
    """Return slack username"""
    return user.slack_username or user.org_username


def get_pagerduty_name(user: User) -> str:
    """Return pagerduty username"""
    return user.pagerduty_username or user.org_username


@retry()
def get_usernames_from_pagerduty(
    pagerduties: Iterable[PagerDutyTargetV1],
    users: Iterable[User],
    usergroup: str,
    pagerduty_map: PagerDutyMap,
) -> list[str]:
    """Return list of usernames from all pagerduties."""
    global error_occurred  # noqa: PLW0603
    all_output_usernames = []
    all_pagerduty_names = [get_pagerduty_name(u) for u in users]
    for pagerduty in pagerduties:
        if pagerduty.schedule_id is not None:
            pd_resource_type = "schedule"
            pd_resource_id = pagerduty.schedule_id
        if pagerduty.escalation_policy_id is not None:
            pd_resource_type = "escalationPolicy"
            pd_resource_id = pagerduty.escalation_policy_id

        pd = pagerduty_map.get(pagerduty.instance.name)
        try:
            pagerduty_names = pd.get_pagerduty_users(pd_resource_type, pd_resource_id)
        except PagerDutyApiException as e:
            logging.error(
                f"[{usergroup}] PagerDuty API error: {e} "
                "(hint: check that pagerduty schedule_id/escalation_policy_id is correct)"
            )
            error_occurred = True
            continue
        if not pagerduty_names:
            continue
        pagerduty_names = [
            name.split("+", 1)[0] for name in pagerduty_names if "nobody" not in name
        ]
        if not pagerduty_names:
            continue
        output_usernames = [
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
                f"[{usergroup}] PagerDuty username not found in app-interface: {not_found_pagerduty_names}"
                " (hint: user files should contain pagerduty_username if it is different than org_username)"
            )
            logging.warning(msg)
        all_output_usernames.extend(output_usernames)

    return all_output_usernames


@retry(max_attempts=10)
def get_slack_usernames_from_owners(
    owners_from_repo: Iterable[str],
    users: Iterable[User],
    usergroup: str,
    repo_owner_class: type[RepoOwners] = RepoOwners,
) -> list[str]:
    """Return list of usernames from all repo owners."""
    all_slack_usernames = []

    for url_ref in owners_from_repo:
        # allow passing repo_url:ref to select different branch
        if url_ref.count(":") == 2:
            url, ref = url_ref.rsplit(":", 1)
        else:
            url = url_ref
            ref = "master"

        with get_git_api(url) as repo_cli:
            if isinstance(repo_cli, GitLabApi):
                user_key = "org_username"
                missing_user_log_method = logging.warning
            elif isinstance(repo_cli, GithubRepositoryApi):
                user_key = "github_username"
                missing_user_log_method = logging.debug
            else:
                raise TypeError(f"{type(repo_cli)} not supported")

            repo_owners = repo_owner_class(git_cli=repo_cli, ref=ref)

            try:
                owners = repo_owners.get_root_owners()
            except UnknownObjectException:
                logging.error(f"ref {ref} not found for repo {url}")
                raise

            all_owners = owners["approvers"] + owners["reviewers"]

            if not all_owners:
                continue

            all_username_keys = [getattr(u, user_key) for u in users]

            slack_usernames = [
                get_slack_username(u)
                for u in users
                if getattr(u, user_key).lower() in [o.lower() for o in all_owners]
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


def get_slack_usernames_from_schedule(schedule: Iterable[ScheduleEntryV1]) -> list[str]:
    """Return list of usernames from all schedules."""
    now = datetime.utcnow()
    all_slack_usernames: list[str] = []
    for entry in schedule:
        start = datetime.strptime(entry.start, DATE_FORMAT)
        end = datetime.strptime(entry.end, DATE_FORMAT)
        if start <= now <= end:
            all_slack_usernames.extend(get_slack_username(u) for u in entry.users)
    return all_slack_usernames


def include_user_to_cluster_usergroup(
    user: UserV1, cluster: ClusterV1, cluster_users: Sequence[str]
) -> bool:
    """Check user has cluster access and should be notified (tag_on_cluster_updates)."""

    if not user_has_cluster_access(user, cluster, cluster_users):
        return False

    if user.tag_on_cluster_updates is not None:
        # if tag_on_cluster_updates is defined
        return user.tag_on_cluster_updates

    # if a user has access via a role
    # check if that role grants access to the current cluster
    # if all roles that grant access to the current cluster also
    # have 'tag_on_cluster_updates: false' - remove the user
    for role in user.roles or []:
        for access in role.access or []:
            if (access.cluster and cluster.name == access.cluster.name) or (
                access.namespace and cluster.name == access.namespace.cluster.name
            ):
                if (
                    role.tag_on_cluster_updates is None
                    or role.tag_on_cluster_updates is True
                ):
                    # found at least one 'tag_on_cluster_updates != false'
                    return True
    return False


def get_desired_state(
    slack_map: SlackMap,
    pagerduty_map: PagerDutyMap,
    permissions: Iterable[PermissionSlackUsergroupV1],
    users: Iterable[User],
    desired_workspace_name: Optional[str],
    desired_usergroup_name: Optional[str],
) -> SlackState:
    """Get the desired state of Slack usergroups."""
    desired_state: SlackState = {}
    for p in permissions:
        if p.skip:
            continue
        if not p.workspace.managed_usergroups:
            continue

        if desired_workspace_name and desired_workspace_name != p.workspace.name:
            continue
        usergroup = p.handle
        if desired_usergroup_name and desired_usergroup_name != usergroup:
            continue
        if usergroup not in p.workspace.managed_usergroups:
            raise KeyError(
                f"[{p.workspace.name}] usergroup {usergroup} \
                    not in managed usergroups {p.workspace.managed_usergroups}"
            )

        slack = slack_map[p.workspace.name].slack
        ugid = slack.get_usergroup_id(usergroup)

        all_user_names = [get_slack_username(u) for r in p.roles or [] for u in r.users]
        slack_usernames_pagerduty = get_usernames_from_pagerduty(
            pagerduties=p.pagerduty or [],
            users=users,
            usergroup=usergroup,
            pagerduty_map=pagerduty_map,
        )
        all_user_names.extend(slack_usernames_pagerduty)

        if p.owners_from_repos:
            slack_usernames_repo = get_slack_usernames_from_owners(
                p.owners_from_repos, users, usergroup
            )
            all_user_names.extend(slack_usernames_repo)

        if p.schedule:
            slack_usernames_schedule = get_slack_usernames_from_schedule(
                p.schedule.schedule
            )
            all_user_names.extend(slack_usernames_schedule)

        user_names = list(set(all_user_names))
        slack_users = {
            SlackObject(pk=pk, name=name)
            for pk, name in slack.get_users_by_names(sorted(user_names)).items()
        }
        slack_channels = {
            SlackObject(pk=pk, name=name)
            for pk, name in slack.get_channels_by_names(
                sorted(p.channels or [])
            ).items()
        }

        try:
            desired_state[p.workspace.name][usergroup].users.update(slack_users)
        except KeyError:
            desired_state.setdefault(p.workspace.name, {})[usergroup] = State(
                workspace=p.workspace.name,
                usergroup=usergroup,
                usergroup_id=ugid,
                users=slack_users,
                channels=slack_channels,
                description=p.description,
            )
    return desired_state


def get_desired_state_cluster_usergroups(
    slack_map: SlackMap,
    clusters: Iterable[ClusterV1],
    users: Iterable[UserV1],
    desired_workspace_name: Optional[str],
    desired_usergroup_name: Optional[str],
) -> SlackState:
    """Get the desired state of Slack usergroups."""
    desired_state: SlackState = {}
    openshift_users_desired_state: list[dict[str, str]] = (
        openshift_users.fetch_desired_state(oc_map=None)
    )
    for cluster in clusters:
        if not integration_is_enabled(QONTRACT_INTEGRATION, cluster):
            logging.debug(
                f"For cluster {cluster.name} the integration {QONTRACT_INTEGRATION} is not enabled. Skipping."
            )
            continue

        desired_cluster_users = [
            u["user"]
            for u in openshift_users_desired_state
            if u["cluster"] == cluster.name
        ]
        cluster_usernames = list({
            get_slack_username(u)
            for u in users
            if include_user_to_cluster_usergroup(u, cluster, desired_cluster_users)
        })
        cluster_user_group = compute_cluster_user_group(cluster.name)
        for workspace, spec in slack_map.items():
            if not spec.slack.channel:
                # spec.slack.channel is None when the integration not properly configured in slack-workspace
                # but then we should not be here
                # so at this point we make just mypy happy
                raise UnknownError("This should never happen.")
            if desired_usergroup_name and desired_usergroup_name != spec.slack.channel:
                continue
            if desired_workspace_name and desired_workspace_name != workspace:
                continue

            ugid = spec.slack.get_usergroup_id(cluster_user_group)
            slack_users = {
                SlackObject(pk=pk, name=name)
                for pk, name in spec.slack.get_users_by_names(
                    sorted(cluster_usernames)
                ).items()
            }
            slack_channels = {
                SlackObject(pk=pk, name=name)
                for pk, name in spec.slack.get_channels_by_names([
                    spec.slack.channel
                ]).items()
            }

            try:
                desired_state[workspace][cluster_user_group].users.update(slack_users)
            except KeyError:
                desired_state.setdefault(workspace, {})[cluster_user_group] = State(
                    workspace=workspace,
                    usergroup=cluster_user_group,
                    usergroup_id=ugid,
                    users=slack_users,
                    channels=slack_channels,
                    description=f"Users with access to the {cluster.name} cluster",
                )
    return desired_state


def _create_usergroups(
    current_ug_state: State,
    desired_ug_state: State,
    slack_client: SlackApi,
    dry_run: bool = True,
) -> None:
    """Create Slack usergroups."""
    global error_occurred  # noqa: PLW0603
    if current_ug_state:
        logging.debug(
            f"[{desired_ug_state.workspace}] Usergroup exists and will not be created {desired_ug_state.usergroup}"
        )
        return

    logging.info([
        "create_usergroup",
        desired_ug_state.workspace,
        desired_ug_state.usergroup,
    ])
    if not dry_run:
        try:
            usergroup_id = slack_client.create_usergroup(desired_ug_state.usergroup)
            desired_ug_state.usergroup_id = usergroup_id
        except SlackApiError as error:
            logging.error(error)
            error_occurred = True


def _update_usergroup_users_from_state(
    current_ug_state: State,
    desired_ug_state: State,
    slack_client: SlackApi,
    dry_run: bool = True,
) -> None:
    """Update the users in a Slack usergroup."""
    global error_occurred  # noqa: PLW0603
    if current_ug_state.users == desired_ug_state.users:
        logging.debug(
            f"No usergroup user changes detected for {desired_ug_state.usergroup}"
        )
        return

    for user in desired_ug_state.users - current_ug_state.users:
        logging.info([
            "add_user_to_usergroup",
            desired_ug_state.workspace,
            desired_ug_state.usergroup,
            user.name,
        ])

    for user in current_ug_state.users - desired_ug_state.users:
        logging.info([
            "del_user_from_usergroup",
            desired_ug_state.workspace,
            desired_ug_state.usergroup,
            user.name,
        ])

    if not dry_run:
        try:
            if not desired_ug_state.usergroup_id:
                logging.info(
                    f"Usergroup {desired_ug_state.usergroup} does not exist yet. Skipping for now."
                )
                return
            slack_client.update_usergroup_users(
                id=desired_ug_state.usergroup_id,
                users_list=sorted([user.pk for user in desired_ug_state.users]),
            )
        except SlackApiError as error:
            # Prior to adding this, we weren't handling failed updates to user
            # groups. Now that we are, it seems like a good idea to start with
            # logging the errors and proceeding rather than blocking time
            # sensitive updates.
            logging.error(error)
            error_occurred = True


def _update_usergroup_from_state(
    current_ug_state: State,
    desired_ug_state: State,
    slack_client: SlackApi,
    dry_run: bool = True,
) -> None:
    """Update a Slack usergroup."""
    global error_occurred  # noqa: PLW0603
    if (
        current_ug_state.channels == desired_ug_state.channels
        and current_ug_state.description == desired_ug_state.description
    ):
        logging.debug(
            f"No usergroup channel/description changes detected for {desired_ug_state.usergroup}",
        )
        return

    for channel in desired_ug_state.channels - current_ug_state.channels:
        logging.info([
            "add_channel_to_usergroup",
            desired_ug_state.workspace,
            desired_ug_state.usergroup,
            channel.name,
        ])

    for channel in current_ug_state.channels - desired_ug_state.channels:
        logging.info([
            "del_channel_from_usergroup",
            desired_ug_state.workspace,
            desired_ug_state.usergroup,
            channel.name,
        ])

    if current_ug_state.description != desired_ug_state.description:
        logging.info([
            "update_usergroup_description",
            desired_ug_state.workspace,
            desired_ug_state.usergroup,
            desired_ug_state.description,
        ])

    if not dry_run:
        try:
            if not desired_ug_state.usergroup_id:
                logging.info(
                    f"Usergroup {desired_ug_state.usergroup} does not exist yet. Skipping for now."
                )
                return
            slack_client.update_usergroup(
                id=desired_ug_state.usergroup_id,
                channels_list=sorted([
                    channel.pk for channel in desired_ug_state.channels
                ]),
                description=desired_ug_state.description,
            )
        except SlackApiError as error:
            logging.error(error)
            error_occurred = True


def act(
    current_state: SlackState,
    desired_state: SlackState,
    slack_map: SlackMap,
    dry_run: bool = True,
) -> None:
    """Reconcile the differences between the desired and current state for
    Slack usergroups."""
    for workspace, desired_ws_state in desired_state.items():
        for usergroup, desired_ug_state in desired_ws_state.items():
            current_ug_state: State = current_state.get(workspace, {}).get(
                usergroup, State()
            )

            _create_usergroups(
                current_ug_state,
                desired_ug_state,
                slack_client=slack_map[workspace].slack,
                dry_run=dry_run,
            )

            _update_usergroup_users_from_state(
                current_ug_state,
                desired_ug_state,
                slack_client=slack_map[workspace].slack,
                dry_run=dry_run,
            )

            _update_usergroup_from_state(
                current_ug_state,
                desired_ug_state,
                slack_client=slack_map[workspace].slack,
                dry_run=dry_run,
            )


def get_permissions(query_func: Callable) -> list[PermissionSlackUsergroupV1]:
    """Return list of slack usergroup permissions from app-interface."""
    return [
        p
        for p in permissions_query(query_func=query_func).permissions
        if isinstance(p, PermissionSlackUsergroupV1)
    ]


def get_users(query_func: Callable) -> list[UserV1]:
    """Return all users from app-interface."""
    return users_query(query_func=query_func).users or []


def get_clusters(query_func: Callable) -> list[ClusterV1]:
    """Return all clusters from app-interface."""
    return clusters_query(query_func=query_func).clusters or []


def run(
    dry_run: bool,
    workspace_name: Optional[str] = None,
    usergroup_name: Optional[str] = None,
) -> None:
    global error_occurred  # noqa: PLW0603
    error_occurred = False

    gqlapi = gql.get_api()
    secret_reader = SecretReader(queries.get_secret_reader_settings())
    init_users = False if usergroup_name else True

    # queries
    permissions = get_permissions(query_func=gqlapi.query)
    pagerduty_instances = get_pagerduty_instances(query_func=gqlapi.query)
    users = get_users(query_func=gqlapi.query)
    clusters = get_clusters(query_func=gqlapi.query)

    # APIs
    slack_map = get_slack_map(
        secret_reader=secret_reader,
        permissions=permissions,
        desired_workspace_name=workspace_name,
    )
    pagerduty_map = get_pagerduty_map(
        secret_reader, pagerduty_instances=pagerduty_instances, init_users=init_users
    )

    # run
    desired_state = get_desired_state(
        slack_map=slack_map,
        pagerduty_map=pagerduty_map,
        permissions=permissions,
        users=users,
        desired_workspace_name=workspace_name,
        desired_usergroup_name=usergroup_name,
    )
    desired_state_cluster_usergroups = get_desired_state_cluster_usergroups(
        slack_map=slack_map,
        clusters=clusters,
        users=users,
        desired_workspace_name=workspace_name,
        desired_usergroup_name=usergroup_name,
    )
    # merge the two desired states recursively
    desired_state = deep_update(desired_state, desired_state_cluster_usergroups)
    current_state = get_current_state(
        slack_map=slack_map,
        desired_workspace_name=workspace_name,
        desired_usergroup_name=usergroup_name,
        cluster_usergroups=[
            compute_cluster_user_group(cluster.name)
            for cluster in clusters
            if integration_is_enabled(QONTRACT_INTEGRATION, cluster)
        ],
    )
    act(
        current_state=current_state,
        desired_state=desired_state,
        slack_map=slack_map,
        dry_run=dry_run,
    )
    if error_occurred:
        logging.error("Error(s) occurred.")
        sys.exit(1)


def early_exit_desired_state(*args: Any, **kwargs: Any) -> dict[str, Any]:
    gqlapi = gql.get_api()
    # exclude user.roles (cluster access roles) with tag_on_cluster_updates: false
    # to speedup PR checks
    users = get_users(gqlapi.query)
    for user in users:
        user.roles = [
            role
            for role in user.roles or []
            if role.tag_on_cluster_updates is not False
        ]
    return {
        "permissions": [p.dict() for p in get_permissions(gqlapi.query)],
        "pagerduty_instances": [
            p.dict() for p in get_pagerduty_instances(gqlapi.query)
        ],
        "users": [u.dict() for u in users],
        "clusters": [c.dict() for c in get_clusters(gqlapi.query)],
    }
