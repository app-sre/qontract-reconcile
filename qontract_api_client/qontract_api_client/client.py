from __future__ import annotations

from clientele import api as clientele_api

from . import config, schemas

client = clientele_api.APIClient(config=config.Config())


@client.post("/api/v1/external/ldap/users/check")
async def ldap_users_check(
    result: schemas.LdapUsersCheckResponse, data: schemas.LdapUsersCheckRequest
) -> schemas.LdapUsersCheckResponse:
    """Check Users Exist

        Check which usernames exist in LDAP (cached, FreeIPA-authenticated).

    Queries LDAP directly using FreeIPA service account credentials
    resolved from Vault. Results are cached for performance.

    Args:
        request: Request with usernames to check and Vault secret reference
        cache: Cache dependency
        secret_manager: Secret manager dependency

    Returns:
        LdapUsersCheckResponse with existence status per username
    """
    return result


@client.get("/api/v1/external/pagerduty/escalation-policies/{policy_id}/users")
async def pagerduty_escalation_policy_users(
    result: schemas.EscalationPolicyUsersResponse,
    policy_id: str,
    secret_manager_url: str,
    path: str,
    field: str | None = None,
    version: int | None = None,
) -> schemas.EscalationPolicyUsersResponse:
    """Get Escalation Policy Users

        Get users in a PagerDuty escalation policy.

    Fetches all users across all escalation rules in the policy.
    Results are cached for performance (TTL configured in settings).

    Args:
        policy_id: PagerDuty escalation policy ID
        instance: PagerDuty instance name

    Returns:
        EscalationPolicyUsersResponse with list of users

    Raises:
        HTTPException:
            - 500 Internal Server Error: If PagerDuty API call fails

    Example:
        GET /api/v1/external/pagerduty/escalation-policies/XYZ789/users?instance=app-sre
        Response:
        {
            "users": [
                {"username": "jsmith"},
                {"username": "mdoe"}
            ]
        }
    """
    return result


@client.get("/api/v1/external/pagerduty/schedules/{schedule_id}/users")
async def pagerduty_schedule_users(
    result: schemas.ScheduleUsersResponse,
    schedule_id: str,
    secret_manager_url: str,
    path: str,
    field: str | None = None,
    version: int | None = None,
) -> schemas.ScheduleUsersResponse:
    """Get Schedule Users

        Get users currently on-call in a PagerDuty schedule.

    Fetches users from the specified schedule using a time window of now + 60 seconds.
    Results are cached for performance (TTL configured in settings).

    Args:
        schedule_id: PagerDuty schedule ID
        instance: PagerDuty instance name

    Returns:
        ScheduleUsersResponse with list of users

    Raises:
        HTTPException:
            - 500 Internal Server Error: If PagerDuty API call fails

    Example:
        GET /api/v1/external/pagerduty/schedules/ABC123/users?instance=app-sre
        Response:
        {
            "users": [
                {"username": "jsmith"},
                {"username": "mdoe"}
            ]
        }
    """
    return result


@client.post("/api/v1/external/slack/chat")
async def slack_chat_post_message(
    result: schemas.ChatResponse, data: schemas.ChatRequest
) -> schemas.ChatResponse:
    """Post Chat

        Post a message to a Slack channel or send a DM to a user.

    Exactly one of `channel` or `user` must be set in the request:
    - `channel`: post to a Slack channel by name
    - `user`: send a DM to a user by org_username

    Args:
        request: Chat request with channel/user, text, and credentials

    Returns:
        ChatResponse with ts, channel, and optional thread_ts

    Raises:
        HTTPException:
            - 404 Not Found: Channel or user not found
            - 502 Bad Gateway: If Slack API call fails
    """
    return result


@client.get("/api/v1/external/slack/conversations/history")
async def slack_conversations_history(
    result: schemas.SlackConversationHistoryResponse,
    secret_manager_url: str,
    path: str,
    workspace_name: str,
    channel: str,
    from_timestamp: int,
    field: str | None = None,
    version: int | None = None,
    to_timestamp: int | None = None,
) -> schemas.SlackConversationHistoryResponse:
    """Get Conversations History

        Get a channel's message history within a timestamp range.

    Args:
        params: workspace_name, channel, from_timestamp/to_timestamp, and secret

    Returns:
        SlackConversationHistoryResponse with messages, newest first

    Raises:
        HTTPException:
            - 404 Not Found: Channel not found
            - 502 Bad Gateway: If Slack API call fails
    """
    return result


@client.post("/api/v1/external/vcs/file-sync")
async def vcs_file_sync(
    result: schemas.FileSyncResponse, data: schemas.FileSyncRequest
) -> schemas.FileSyncResponse:
    """File Sync

        Reconcile file states in a VCS repository.

    Creates a merge request with the given file operations,
    deduplicating by MR title. Does not read current file state —
    relies on GitLab/GitHub for validation.
    """
    return result


@client.get("/api/v1/external/vcs/repos/file")
async def vcs_get_file(
    result: schemas.GetFileResponse,
    secret_manager_url: str,
    path: str,
    repo_url: str,
    file_path: str,
    ref: str,
    field: str | None = None,
    version: int | None = None,
) -> schemas.GetFileResponse:
    """Get File

    Read a file from a VCS repository.
    """
    return result


@client.get("/api/v1/external/vcs/repos/owners")
async def vcs_repo_owners(
    result: schemas.RepoOwnersResponse,
    secret_manager_url: str,
    path: str,
    repo_url: str,
    ref: str,
    field: str | None = None,
    version: int | None = None,
    owners_file: str | None = None,
) -> schemas.RepoOwnersResponse:
    """Get Repo Owners

        Get OWNERS file data from a Git repository.

    Fetches OWNERS file approvers and reviewers from GitHub or GitLab repositories.
    Results are cached for performance (TTL configured in settings).
    """
    return result


@client.post("/api/v1/integrations/github-owners/reconcile")
async def github_owners(
    result: schemas.GithubOwnersTaskResponse, data: schemas.GithubOwnersReconcileRequest
) -> schemas.GithubOwnersTaskResponse:
    """Github Owners

        Queue a GitHub owners reconciliation task.

    This endpoint always queues a background task and returns immediately
    with a task_id. Use GET /reconcile/{task_id} to retrieve the result.

    Args:
        reconcile_request: Reconciliation request with desired owner state
        current_user: Authenticated user (from JWT token)
        request: FastAPI Request object (used to generate status_url)

    Returns:
        GithubOwnersTaskResponse with task_id and status_url
    """
    return result


@client.get("/api/v1/integrations/github-owners/reconcile/{task_id}")
async def github_owners_task_status(
    result: schemas.GithubOwnersTaskResult,
    task_id: str,
    timeout: int | None = None,
) -> schemas.GithubOwnersTaskResult:
    """Github Owners Task Status

        Retrieve the reconciliation result (blocking or non-blocking).

    **Non-blocking mode (default):** Returns immediate status (pending/success/failed)
    **Blocking mode (with timeout):** Waits up to timeout seconds, returns 408 if still pending

    Args:
        task_id: Task ID from POST /reconcile response
        current_user: Authenticated user (from JWT token)
        timeout: Maximum seconds to wait (default: None = non-blocking)

    Returns:
        GithubOwnersTaskResult with status, actions, applied_count, and errors

    Raises:
        HTTPException:
            - 404 Not Found: Task ID not found
            - 408 Request Timeout: Task still pending after timeout (blocking mode only)
    """
    return result


@client.post("/api/v1/integrations/glitchtip-project-alerts/reconcile")
async def glitchtip_project_alerts(
    result: schemas.GlitchtipProjectAlertsTaskResponse,
    data: schemas.GlitchtipProjectAlertsReconcileRequest,
) -> schemas.GlitchtipProjectAlertsTaskResponse:
    """Glitchtip Project Alerts

        Queue Glitchtip project alerts reconciliation task.

    This endpoint always queues a background task and returns immediately
    with a task_id. Use GET /reconcile/{task_id} to retrieve the result.

    Args:
        reconcile_request: Reconciliation request with desired state
        current_user: Authenticated user (from JWT token)
        request: FastAPI Request object (used to generate status_url)

    Returns:
        GlitchtipProjectAlertsTaskResponse with task_id and status_url
    """
    return result


@client.get("/api/v1/integrations/glitchtip-project-alerts/reconcile/{task_id}")
async def glitchtip_project_alerts_task_status(
    result: schemas.GlitchtipProjectAlertsTaskResult,
    task_id: str,
    timeout: int | None = None,
) -> schemas.GlitchtipProjectAlertsTaskResult:
    """Glitchtip Project Alerts Task Status

        Retrieve reconciliation result (blocking or non-blocking).

    **Non-blocking mode (default):** Returns immediate status (pending/success/failed)
    **Blocking mode (with timeout):** Waits up to timeout seconds, returns 408 if still pending

    Args:
        task_id: Task ID from POST /reconcile response
        current_user: Authenticated user (from JWT token)
        timeout: Maximum seconds to wait (default: None = non-blocking)

    Returns:
        GlitchtipProjectAlertsTaskResult with status, actions, applied_count, and errors

    Raises:
        HTTPException:
            - 404 Not Found: Task ID not found
            - 408 Request Timeout: Task still pending after timeout (blocking mode only)
    """
    return result


@client.post("/api/v1/integrations/glitchtip/reconcile")
async def glitchtip(
    result: schemas.GlitchtipTaskResponse, data: schemas.GlitchtipReconcileRequest
) -> schemas.GlitchtipTaskResponse:
    """Glitchtip Reconcile

        Queue Glitchtip reconciliation task.

    This endpoint always queues a background task and returns immediately
    with a task_id. Use GET /reconcile/{task_id} to retrieve the result.

    Args:
        reconcile_request: Reconciliation request with desired state
        current_user: Authenticated user (from JWT token)
        request: FastAPI Request object (used to generate status_url)

    Returns:
        GlitchtipTaskResponse with task_id and status_url
    """
    return result


@client.get("/api/v1/integrations/glitchtip/reconcile/{task_id}")
async def glitchtip_task_status(
    result: schemas.GlitchtipTaskResult,
    task_id: str,
    timeout: int | None = None,
) -> schemas.GlitchtipTaskResult:
    """Glitchtip Reconcile Task Status

        Retrieve reconciliation result (blocking or non-blocking).

    **Non-blocking mode (default):** Returns immediate status
    **Blocking mode (with timeout):** Waits up to timeout seconds

    Args:
        task_id: Task ID from POST /reconcile response
        current_user: Authenticated user (from JWT token)
        timeout: Maximum seconds to wait (default: None = non-blocking)

    Returns:
        GlitchtipTaskResult with status, actions, applied_count, and errors
    """
    return result


@client.post("/api/v1/integrations/openshift-namespaces/reconcile")
async def openshift_namespaces(
    result: schemas.OpenShiftNamespacesTaskResponse,
    data: schemas.OpenShiftNamespacesReconcileRequest,
) -> schemas.OpenShiftNamespacesTaskResponse:
    """Openshift Namespaces Reconcile

    Queue openshift-namespaces reconciliation task.
    """
    return result


@client.get("/api/v1/integrations/openshift-namespaces/reconcile/{task_id}")
async def openshift_namespaces_task_status(
    result: schemas.OpenShiftNamespacesTaskResult,
    task_id: str,
    timeout: int | None = None,
) -> schemas.OpenShiftNamespacesTaskResult:
    """Openshift Namespaces Reconcile Task Status

    Retrieve reconciliation result (blocking or non-blocking).
    """
    return result


@client.post("/api/v1/integrations/slack-usergroups/reconcile")
async def slack_usergroups(
    result: schemas.SlackUsergroupsTaskResponse,
    data: schemas.SlackUsergroupsReconcileRequest,
) -> schemas.SlackUsergroupsTaskResponse:
    """Slack Usergroups

        Queue Slack usergroups reconciliation task.

    This endpoint always queues a background task and returns immediately
    with a task_id. Use GET /reconcile/{task_id} to retrieve the result.

    Args:
        reconcile_request: Reconciliation request with desired state
        current_user: Authenticated user (from JWT token)
        request: FastAPI Request object (used to generate status_url)

    Returns:
        SlackUsergroupsTaskResponse with task_id and status_url
    """
    return result


@client.get("/api/v1/integrations/slack-usergroups/reconcile/{task_id}")
async def slack_usergroups_task_status(
    result: schemas.SlackUsergroupsTaskResult,
    task_id: str,
    timeout: int | None = None,
) -> schemas.SlackUsergroupsTaskResult:
    """Slack Usergroups Task Status

        Retrieve reconciliation result (blocking or non-blocking).

    **Non-blocking mode (default):** Returns immediate status (pending/success/failed)
    **Blocking mode (with timeout):** Waits up to timeout seconds, returns 408 if still pending

    Args:
        task_id: Task ID from POST /reconcile response
        current_user: Authenticated user (from JWT token)
        timeout: Maximum seconds to wait (default: None = non-blocking)

    Returns:
        SlackUsergroupsTaskResult with status, actions, applied_count, and errors

    Raises:
        HTTPException:
            - 404 Not Found: Task ID not found
            - 408 Request Timeout: Task still pending after timeout (blocking mode only)
    """
    return result


@client.get("/health/live")
async def liveness(result: schemas.ResponseLiveness) -> schemas.ResponseLiveness:
    """Liveness

    Liveness probe - returns 200 if service is running.
    """
    return result


@client.get("/health/ready")
async def readiness(result: schemas.HealthResponse) -> schemas.HealthResponse:
    """Readiness

    Readiness probe - returns 200 if service is ready to accept requests.
    """
    return result
