from __future__ import annotations

import enum
import inspect
import typing

import pydantic
from clientele.schemas import ListResponse  # noqa


class ChatRequest(pydantic.BaseModel):
    channel: str | None = None
    icon_emoji: str | None = None
    icon_url: str | None = None
    secret: Secret
    text: str
    thread_ts: str | None = None
    user: str | None = None
    username: str | None = None
    workspace_name: str


class ChatTaskResponse(pydantic.BaseModel):
    id: str
    status: TaskStatus | None = None
    status_url: str


class ChatTaskResult(pydantic.BaseModel):
    actions: list[str] = []
    applied_count: int = 0
    channel: str | None = None
    errors: list[str] = []
    status: TaskStatus
    thread_ts: str | None = None
    ts: str | None = None


class ClusterNamespaces(pydantic.BaseModel):
    automation_token: Secret
    cluster_name: str
    insecure_skip_tls_verify: bool = False
    namespaces: list[DesiredNamespace] | None = None
    server_url: str


class CreateNamespaceAction(pydantic.BaseModel):
    action_type: typing.Literal["create_namespace"] = "create_namespace"
    cluster: str
    namespace: str


class DeleteNamespaceAction(pydantic.BaseModel):
    action_type: typing.Literal["delete_namespace"] = "delete_namespace"
    cluster: str
    namespace: str


class DesiredNamespace(pydantic.BaseModel):
    delete: bool = False
    name: str


class EscalationPolicyUsersResponse(pydantic.BaseModel):
    users: list[PagerDutyUser]


class FileSyncCreate(pydantic.BaseModel):
    action: typing.Literal["create"] = "create"
    commit_message: str
    content: str
    path: str


class FileSyncDelete(pydantic.BaseModel):
    action: typing.Literal["delete"] = "delete"
    commit_message: str
    path: str


class FileSyncRequest(pydantic.BaseModel):
    auto_merge: bool = False
    description: str = ""
    file_operations: list[
        typing.Annotated[
            FileSyncCreate | FileSyncUpdate | FileSyncDelete,
            pydantic.Field(discriminator="action"),
        ]
    ]
    labels: list[str] | None = None
    repo_url: str
    target_branch: str
    title: str
    token: Secret


class FileSyncResponse(pydantic.BaseModel):
    mr_url: str | None = None
    status: FileSyncStatus


class FileSyncStatus(str, enum.Enum):
    MR_CREATED = "mr_created"
    MR_EXISTS = "mr_exists"


class FileSyncUpdate(pydantic.BaseModel):
    action: typing.Literal["update"] = "update"
    commit_message: str
    content: str
    path: str


class GIInstance(pydantic.BaseModel):
    automation_user_email: Secret
    console_url: str
    max_retries: int = 3
    name: str
    organizations: list[GIOrganization] = []
    read_timeout: int = 30
    token: Secret


class GIOrganization(pydantic.BaseModel):
    name: str
    projects: list[GIProject] = []
    teams: list[GlitchtipTeam] = []
    users: list[GlitchtipUser] = []


class GIProject(pydantic.BaseModel):
    event_throttle_rate: int = 0
    name: str
    platform: str | None = None
    slug: str
    teams: list[str] = []


class GetFileResponse(pydantic.BaseModel):
    content: str


class GithubOrgDesiredState(pydantic.BaseModel):
    base_url: str = "https://api.github.com"
    org_name: str
    owners: list[str]
    token: Secret


class GithubOwnerActionAddOwner(pydantic.BaseModel):
    action_type: typing.Literal["add_owner"] = "add_owner"
    org_name: str
    username: str


class GithubOwnersReconcileRequest(pydantic.BaseModel):
    dry_run: bool = True
    organizations: list[GithubOrgDesiredState]


class GithubOwnersTaskResponse(pydantic.BaseModel):
    id: str
    status: TaskStatus | None = None
    status_url: str


class GithubOwnersTaskResult(pydantic.BaseModel):
    actions: list[
        typing.Annotated[
            GithubOwnerActionAddOwner,
            pydantic.Field(discriminator="action_type"),
        ]
    ] = []
    applied_actions: list[
        typing.Annotated[
            GithubOwnerActionAddOwner,
            pydantic.Field(discriminator="action_type"),
        ]
    ] = []
    applied_count: int = 0
    errors: list[str] = []
    status: TaskStatus


class GlitchtipActionAddProjectToTeam(pydantic.BaseModel):
    action_type: typing.Literal["add_project_to_team"] = "add_project_to_team"
    instance: str
    organization: str
    project_slug: str
    team_slug: str


class GlitchtipActionAddUserToTeam(pydantic.BaseModel):
    action_type: typing.Literal["add_user_to_team"] = "add_user_to_team"
    email: str
    instance: str
    organization: str
    pk: int | None = None
    team_slug: str


class GlitchtipActionCreateOrganization(pydantic.BaseModel):
    action_type: typing.Literal["create_organization"] = "create_organization"
    instance: str
    organization: str


class GlitchtipActionCreateProject(pydantic.BaseModel):
    action_type: typing.Literal["create_project"] = "create_project"
    event_throttle_rate: int = 0
    instance: str
    organization: str
    platform: str | None = None
    project_name: str
    teams: list[str] | None = None


class GlitchtipActionCreateTeam(pydantic.BaseModel):
    action_type: typing.Literal["create_team"] = "create_team"
    instance: str
    organization: str
    team_slug: str


class GlitchtipActionDeleteOrganization(pydantic.BaseModel):
    action_type: typing.Literal["delete_organization"] = "delete_organization"
    instance: str
    organization: str


class GlitchtipActionDeleteProject(pydantic.BaseModel):
    action_type: typing.Literal["delete_project"] = "delete_project"
    instance: str
    organization: str
    project_slug: str


class GlitchtipActionDeleteTeam(pydantic.BaseModel):
    action_type: typing.Literal["delete_team"] = "delete_team"
    instance: str
    organization: str
    team_slug: str


class GlitchtipActionDeleteUser(pydantic.BaseModel):
    action_type: typing.Literal["delete_user"] = "delete_user"
    email: str
    instance: str
    organization: str
    pk: int


class GlitchtipActionInviteUser(pydantic.BaseModel):
    action_type: typing.Literal["invite_user"] = "invite_user"
    email: str
    instance: str
    organization: str
    role: str


class GlitchtipActionRemoveProjectFromTeam(pydantic.BaseModel):
    action_type: typing.Literal["remove_project_from_team"] = "remove_project_from_team"
    instance: str
    organization: str
    project_slug: str
    team_slug: str


class GlitchtipActionRemoveUserFromTeam(pydantic.BaseModel):
    action_type: typing.Literal["remove_user_from_team"] = "remove_user_from_team"
    email: str
    instance: str
    organization: str
    pk: int
    team_slug: str


class GlitchtipActionUpdateProject(pydantic.BaseModel):
    action_type: typing.Literal["update_project"] = "update_project"
    event_throttle_rate: int = 0
    instance: str
    name: str
    organization: str
    platform: str | None = None
    project_slug: str


class GlitchtipActionUpdateUserRole(pydantic.BaseModel):
    action_type: typing.Literal["update_user_role"] = "update_user_role"
    email: str
    instance: str
    organization: str
    pk: int
    role: str


class GlitchtipAlertActionCreate(pydantic.BaseModel):
    action_type: typing.Literal["create"] = "create"
    alert_name: str
    instance: str
    organization: str
    project: str


class GlitchtipAlertActionDelete(pydantic.BaseModel):
    action_type: typing.Literal["delete"] = "delete"
    alert_name: str
    instance: str
    organization: str
    project: str


class GlitchtipAlertActionUpdate(pydantic.BaseModel):
    action_type: typing.Literal["update"] = "update"
    alert_name: str
    instance: str
    organization: str
    project: str


class GlitchtipInstance(pydantic.BaseModel):
    console_url: str
    max_retries: int = 3
    name: str
    organizations: list[GlitchtipOrganization] = []
    read_timeout: int = 30
    token: Secret


class GlitchtipOrganization(pydantic.BaseModel):
    name: str
    projects: list[GlitchtipProject] = []


class GlitchtipProject(pydantic.BaseModel):
    alerts: list[GlitchtipProjectAlert] = []
    name: str
    slug: str = ""


class GlitchtipProjectAlert(pydantic.BaseModel):
    name: str
    quantity: int
    recipients: list[GlitchtipProjectAlertRecipient] = []
    timespan_minutes: int


class GlitchtipProjectAlertRecipient(pydantic.BaseModel):
    recipient_type: RecipientType
    url: str = ""


class GlitchtipProjectAlertsReconcileRequest(pydantic.BaseModel):
    dry_run: bool = True
    instances: list[GlitchtipInstance]


class GlitchtipProjectAlertsTaskResponse(pydantic.BaseModel):
    id: str
    status: TaskStatus | None = None
    status_url: str


class GlitchtipProjectAlertsTaskResult(pydantic.BaseModel):
    actions: list[
        typing.Annotated[
            GlitchtipAlertActionCreate
            | GlitchtipAlertActionUpdate
            | GlitchtipAlertActionDelete,
            pydantic.Field(discriminator="action_type"),
        ]
    ] = []
    applied_actions: list[
        typing.Annotated[
            GlitchtipAlertActionCreate
            | GlitchtipAlertActionUpdate
            | GlitchtipAlertActionDelete,
            pydantic.Field(discriminator="action_type"),
        ]
    ] = []
    applied_count: int = 0
    errors: list[str] = []
    status: TaskStatus


class GlitchtipReconcileRequest(pydantic.BaseModel):
    dry_run: bool = True
    instances: list[GIInstance]


class GlitchtipTaskResponse(pydantic.BaseModel):
    id: str
    status: TaskStatus | None = None
    status_url: str


class GlitchtipTaskResult(pydantic.BaseModel):
    actions: list[
        typing.Annotated[
            GlitchtipActionCreateOrganization
            | GlitchtipActionDeleteOrganization
            | GlitchtipActionInviteUser
            | GlitchtipActionDeleteUser
            | GlitchtipActionUpdateUserRole
            | GlitchtipActionCreateTeam
            | GlitchtipActionDeleteTeam
            | GlitchtipActionAddUserToTeam
            | GlitchtipActionRemoveUserFromTeam
            | GlitchtipActionCreateProject
            | GlitchtipActionUpdateProject
            | GlitchtipActionDeleteProject
            | GlitchtipActionAddProjectToTeam
            | GlitchtipActionRemoveProjectFromTeam,
            pydantic.Field(discriminator="action_type"),
        ]
    ] = []
    applied_actions: list[
        typing.Annotated[
            GlitchtipActionCreateOrganization
            | GlitchtipActionDeleteOrganization
            | GlitchtipActionInviteUser
            | GlitchtipActionDeleteUser
            | GlitchtipActionUpdateUserRole
            | GlitchtipActionCreateTeam
            | GlitchtipActionDeleteTeam
            | GlitchtipActionAddUserToTeam
            | GlitchtipActionRemoveUserFromTeam
            | GlitchtipActionCreateProject
            | GlitchtipActionUpdateProject
            | GlitchtipActionDeleteProject
            | GlitchtipActionAddProjectToTeam
            | GlitchtipActionRemoveProjectFromTeam,
            pydantic.Field(discriminator="action_type"),
        ]
    ] = []
    applied_count: int = 0
    errors: list[str] = []
    status: TaskStatus


class GlitchtipTeam(pydantic.BaseModel):
    name: str
    users: list[GlitchtipUser] = []


class GlitchtipUser(pydantic.BaseModel):
    email: str
    role: str = "member"


class HTTPValidationError(pydantic.BaseModel):
    detail: list[ValidationError]


class HealthResponse(pydantic.BaseModel):
    components: dict[str, typing.Any] | None = None
    service: str
    status: str
    version: str


class HealthStatus(pydantic.BaseModel):
    message: str | None = None
    status: str


class LdapDirectSecret(pydantic.BaseModel):
    base_dn: str
    field: str | None = None
    path: str
    secret_manager_url: str
    server_url: str
    version: int | None = None


class LdapUserStatus(pydantic.BaseModel):
    exists: bool
    username: str


class LdapUsersCheckRequest(pydantic.BaseModel):
    secret: LdapDirectSecret
    usernames: list[str]


class LdapUsersCheckResponse(pydantic.BaseModel):
    users: list[LdapUserStatus]


class NotificationAddUser(pydantic.BaseModel):
    action: typing.Literal["add-user"] = "add-user"
    message: str


class NotificationRemoveUser(pydantic.BaseModel):
    action: typing.Literal["remove-user"] = "remove-user"
    message: str


class OpenShiftNamespacesReconcileRequest(pydantic.BaseModel):
    clusters: list[ClusterNamespaces]
    dry_run: bool = True


class OpenShiftNamespacesTaskResponse(pydantic.BaseModel):
    id: str
    status: TaskStatus
    status_url: str


class OpenShiftNamespacesTaskResult(pydantic.BaseModel):
    actions: list[
        typing.Annotated[
            CreateNamespaceAction | DeleteNamespaceAction,
            pydantic.Field(discriminator="action_type"),
        ]
    ] = []
    applied_actions: list[
        typing.Annotated[
            CreateNamespaceAction | DeleteNamespaceAction,
            pydantic.Field(discriminator="action_type"),
        ]
    ] = []
    applied_count: int = 0
    errors: list[str] = []
    status: TaskStatus


class PagerDutyUser(pydantic.BaseModel):
    username: str


class RecipientType(str, enum.Enum):
    EMAIL = "email"
    WEBHOOK = "webhook"


class RepoOwnersResponse(pydantic.BaseModel):
    approvers: list[str] | None = None
    provider: VCSProvider
    reviewers: list[str] | None = None


class ScheduleUsersResponse(pydantic.BaseModel):
    users: list[PagerDutyUser]


class Secret(pydantic.BaseModel):
    field: str | None = None
    path: str
    secret_manager_url: str
    version: int | None = None


class SlackConversationHistoryResponse(pydantic.BaseModel):
    messages: list[SlackMessageResponse]


class SlackMessageAttachmentResponse(pydantic.BaseModel):
    text: str | None
    title: str | None


class SlackMessageReactionResponse(pydantic.BaseModel):
    count: int = 0
    name: str


class SlackMessageResponse(pydantic.BaseModel):
    attachments: list[SlackMessageAttachmentResponse] | None = None
    reactions: list[SlackMessageReactionResponse] | None = None
    reply_count: int = 0
    subtype: str | None = None
    text: str = ""
    ts: str
    username: str | None = None


class SlackUsergroup(pydantic.BaseModel):
    config: SlackUsergroupConfig
    handle: str


class SlackUsergroupActionCreate(pydantic.BaseModel):
    action_type: typing.Literal["create"] = "create"
    description: str
    usergroup: str
    users: list[str]
    workspace: str


class SlackUsergroupActionUpdateMetadata(pydantic.BaseModel):
    action_type: typing.Literal["update_metadata"] = "update_metadata"
    channels: list[str]
    description: str
    usergroup: str
    workspace: str


class SlackUsergroupActionUpdateUsers(pydantic.BaseModel):
    action_type: typing.Literal["update_users"] = "update_users"
    notifications: (
        list[
            typing.Annotated[
                NotificationAddUser | NotificationRemoveUser,
                pydantic.Field(discriminator="action"),
            ]
        ]
        | None
    ) = None
    usergroup: str
    users: list[str]
    users_to_add: list[str]
    users_to_remove: list[str]
    workspace: str


class SlackUsergroupConfig(pydantic.BaseModel):
    channels: list[str] = []
    description: str = ""
    notifications: list[
        typing.Annotated[
            NotificationAddUser | NotificationRemoveUser,
            pydantic.Field(discriminator="action"),
        ]
    ] = []
    users: list[str] = []


class SlackUsergroupsReconcileRequest(pydantic.BaseModel):
    dry_run: bool = True
    workspaces: list[SlackWorkspace]


class SlackUsergroupsTaskResponse(pydantic.BaseModel):
    id: str
    status: TaskStatus | None = None
    status_url: str


class SlackUsergroupsTaskResult(pydantic.BaseModel):
    actions: list[
        SlackUsergroupActionCreate
        | SlackUsergroupActionUpdateUsers
        | SlackUsergroupActionUpdateMetadata
    ] = []
    applied_actions: list[
        SlackUsergroupActionCreate
        | SlackUsergroupActionUpdateUsers
        | SlackUsergroupActionUpdateMetadata
    ] = []
    applied_count: int = 0
    errors: list[str] = []
    status: TaskStatus


class SlackWorkspace(pydantic.BaseModel):
    managed_usergroups: list[str]
    name: str
    token: Secret
    usergroups: list[SlackUsergroup]


class TaskStatus(str, enum.Enum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class VCSProvider(str, enum.Enum):
    GITHUB = "github"
    GITLAB = "gitlab"


class ValidationError(pydantic.BaseModel):
    ctx: dict[str, typing.Any] | None = None
    input: typing.Any | None = None
    loc: list[str | int]
    msg: str
    type_: str = pydantic.Field(alias="type")

    model_config = pydantic.ConfigDict(populate_by_name=True)


class ResponseLiveness(pydantic.BaseModel):
    pass


def get_subclasses_from_same_file() -> list[type[pydantic.BaseModel]]:
    """
    Due to how Python declares classes in a module,
    we need to update_forward_refs for all the schemas generated
    here in the situation where there are nested classes.
    """
    calling_frame = inspect.currentframe()
    if not calling_frame:
        return []
    else:
        calling_frame = calling_frame.f_back
    module = inspect.getmodule(calling_frame)

    subclasses = []
    for _, c in inspect.getmembers(module):
        if (
            inspect.isclass(c)
            and issubclass(c, pydantic.BaseModel)
            and c != pydantic.BaseModel
        ):
            subclasses.append(c)

    return subclasses


subclasses: list[type[pydantic.BaseModel]] = get_subclasses_from_same_file()
for c in subclasses:
    c.model_rebuild()
