# ADR-003: Async-Only API with Blocking GET Pattern

**Status:** Accepted
**Date:** 2025-11-19
**Authors:** cassing
**Supersedes:** ADR-003 v1 (direct-vs-queued-execution-modes)
**Superseded by:** N/A

## Context

The qontract-api serves two distinct use cases with different requirements:

### Use Case 1: MR Validation (GitLab Merge Requests)

- **Purpose**: Validate proposed changes before merging
- **Requirements**:
  - **Quick response**: MR job needs result within minutes (< 5 minutes)
  - **Dry-run only**: Never apply changes, only calculate actions
  - **Result retrieval**: Job must get the calculated actions
  - **Log output**: Display actions in MR comment

### Use Case 2: Production Runs (Scheduled Jobs)

- **Purpose**: Apply changes to external systems
- **Requirements**:
  - **Background execution**: Can take longer (> 10 minutes okay)
  - **Apply changes**: Actually modify external systems
  - **Fire-and-forget**: Client doesn't need immediate result
  - **Status tracking**: Optionally check progress via task_id

### Problem

Initial approach (ADR-003 v1) used an `execution_mode` parameter:

- `execution_mode="direct"`: Execute synchronously, return result
- `execution_mode="queued"`: Queue task, return task_id

**Issues with parameter-based approach:**

1. **Two execution paths**: Router had branching logic for direct vs queued
2. **Inconsistent responses**: Different response types based on parameter
3. **FastAPI timeout risk**: Direct mode could timeout for long operations
4. **Unclear semantics**: Parameter-based control is less RESTful

**Better approach**: Use HTTP verbs to control behavior

- **POST**: Create task (always async, always returns task_id)
- **GET**: Retrieve result (blocks until complete or timeout)

## Decision

**Use async-only API pattern where POST creates tasks and GET retrieves results with blocking behavior.**

### POST: Always Async (Queue Task)

All reconciliation POST requests queue a background background task and return immediately.

```http
POST /api/v1/integrations/slack-usergroups/reconcile
Content-Type: application/json

{
  "workspaces": [...],
  "dry_run": true
}

Response: 202 Accepted
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "queued",
  "status_url": "/api/v1/integrations/slack-usergroups/reconcile/550e8400-e29b-41d4-a716-446655440000"
}
```

**Characteristics:**

- Always returns `202 Accepted`
- Always queues background task
- Returns immediately (no waiting)
- Works for both dry-run and apply modes

### GET: Retrieve Result (Blocking or Non-Blocking)

GET request retrieves task status and result. Behavior depends on `timeout` parameter.

#### Non-Blocking (Default - No Timeout)

```http
GET /api/v1/integrations/slack-usergroups/reconcile/550e8400-e29b-41d4-a716-446655440000
Authorization: Bearer <token>

Response: 200 OK (always, returns current status)
{
  "status": "pending",  // or "success", "failed"
  "actions": [],
  "applied_count": 0,
  "errors": null
}
```

#### Blocking (With Timeout)

```http
GET /api/v1/integrations/slack-usergroups/reconcile/550e8400-e29b-41d4-a716-446655440000?timeout=60
Authorization: Bearer <token>

Response: 200 OK (when complete within timeout)
{
  "status": "success",  // or "failed"
  "actions": [
    {"action_type": "update_users", "workspace": "...", ...},
    {"action_type": "update_channels", ...}
  ],
  "applied_count": 5,
  "errors": null
}

Response: 408 Request Timeout (if still pending after timeout)
{
  "detail": "Task still pending after 60s"
}
```

**Characteristics:**

- **Without timeout (default)**: Returns immediately with current status (pending/success/failed)
- **With timeout**: Blocks until task completes OR timeout expires
- `timeout` query parameter: Optional (default: None = non-blocking, max: from config)
- Returns `200 OK` with status+result when complete
- Returns `408 Request Timeout` only in blocking mode if still pending
- Polls background task status internally (blocking mode only)

## Typical Usage Patterns

### MR Validation

```python
# reconcile/slack_usergroups_api.py (called from GitLab MR job)

# 1. Queue task
response = api_client.post("/reconcile", json={
    "workspaces": desired_state,
    "dry_run": True,
})

task_id = response["task_id"]
status_url = response["status_url"]

# 2. Block until result (with timeout)
result = api_client.get(status_url, params={"timeout": 120})

# 3. Display actions in MR comment
for action in result["actions"]:
    print(f"Would {action['action_type']}: {action['usergroup']}")
```

### Production Run (Fire-and-Forget)

```python
# reconcile/slack_usergroups_api.py (called from scheduled job)

# Queue task
response = api_client.post("/reconcile", json={
    "workspaces": desired_state,
    "dry_run": False,
})

task_id = response["task_id"]
logging.info(f"Queued reconciliation: {task_id}")

# Don't wait for result - let it run in background
```

### Production Run (Wait for Completion)

```python
# reconcile/slack_usergroups_api.py (with result checking)

# Queue task
response = api_client.post("/reconcile", json={
    "workspaces": desired_state,
    "dry_run": False,
})

# Wait up to 5 minutes for completion
try:
    result = api_client.get(response["status_url"], params={"timeout": 300})
    logging.info(f"Applied {result['applied_count']} actions")
except Timeout:
    logging.warning(f"Task {response['task_id']} still running, will complete in background")
```

## Alternatives Considered

### Alternative 1: Parameter-Based Execution Mode (Previous Approach)

Use `execution_mode` parameter to control sync vs async.

**Pros:**

- Single POST endpoint
- Clear intent with parameter

**Cons:**

- **Two execution paths**: Complex router logic with branching
- **Inconsistent responses**: Different types based on parameter value
- **Less RESTful**: Parameters controlling behavior instead of HTTP verbs
- **FastAPI timeout risk**: Direct mode could timeout in API worker

### Alternative 2: Separate Endpoints

Two endpoints: `/reconcile` (sync) and `/reconcile-async` (async).

**Pros:**

- Clear separation
- No parameter needed

**Cons:**

- **Code duplication**: Two endpoints, same logic
- **Unclear which to use**: Not obvious from endpoint names
- **More API surface**: Two endpoints to document/maintain

### Alternative 3: Always Queue + Manual Polling

Always queue tasks, client polls `/tasks/{task_id}` manually.

**Pros:**

- Simple: always async
- No blocking needed

**Cons:**

- **Polling complexity**: Client must implement retry/backoff logic
- **Slower MR feedback**: Extra network round-trips
- **More client code**: Every client reimplements polling

### Alternative 4: Async-Only with Blocking GET (Selected)

POST always queues, GET blocks until complete.

**Pros:**

- **RESTful**: HTTP verbs control behavior (POST creates, GET retrieves)
- **Single execution path**: Router always queues task
- **Simpler router**: No branching logic based on parameters
- **Consistent responses**: POST always returns task_id, GET always returns result
- **No FastAPI timeout**: Blocking happens in GET handler, not task execution
- **Client simplicity**: MR jobs just POST + GET (no polling logic)
- **Flexible**: Fire-and-forget or wait-for-result, client chooses

**Cons:**

- **Blocking in API**: GET handler blocks while polling Celery
  - **Mitigation**: Timeout parameter limits blocking time (default 60s, max 300s)
  - GET handler just polls task status, doesn't execute the reconciliation
- **Two requests**: Client makes POST then GET instead of one POST
  - **Mitigation**: Standard RESTful pattern, minimal overhead
  - MR jobs already need result, so two requests is acceptable

## Consequences

### Positive

1. **RESTful design**: POST creates resources, GET retrieves them
2. **Simpler router**: No branching logic, always queue task
3. **Consistent responses**: POST → task_id, GET → result
4. **Type-safe**: Single response type per endpoint
5. **No FastAPI timeout**: Long operations run in Celery, not API worker
6. **Client flexibility**: Fire-and-forget (POST only) or wait-for-result (POST + GET)
7. **Explicit timeout control**: Client specifies how long to wait
8. **No polling complexity**: Blocking GET handles polling internally

### Negative

1. **Blocking in API worker**: GET handler polls background task status
   - **Mitigation**: Timeout parameter limits blocking time (max 300s)
   - GET handler doesn't execute reconciliation, just polls status
   - Separate API workers from background workers prevents resource contention

2. **Two requests instead of one**: Client must POST then GET
   - **Mitigation**: Standard RESTful pattern, minimal overhead
   - Fire-and-forget clients can skip GET entirely

3. **Minimum latency overhead**: Even fast tasks require two requests
   - **Mitigation**: Acceptable tradeoff for consistent API design
   - Most reconciliations take >1 second anyway (Slack API calls)

## Implementation Guidelines

### API Models

```python
from pydantic import BaseModel, Field

# POST request (no execution_mode parameter)
class SlackUsergroupsReconcileRequest(BaseModel):
    """Request model for reconciliation endpoint."""
    workspaces: list[SlackWorkspace]
    dry_run: bool = True

# POST response
class SlackUsergroupsTaskResponse(BaseModel):
    """Response when task is queued."""
    task_id: str
    status: str = "queued"
    status_url: str

# GET response
class SlackUsergroupsTaskResult(BaseModel):
    """Response when task is complete."""
    actions: list[SlackUsergroupAction] = []
    applied_count: int = 0
    errors: list[str] | None = None
```

### API Router

```python
@router.post(
    "/reconcile",
    response_model=SlackUsergroupsTaskResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_reconcile_task(
    request: SlackUsergroupsReconcileRequest,
    current_user: UserDep,
) -> SlackUsergroupsTaskResponse:
    """Queue reconciliation task (always async)."""

    # Queue background task
    task = reconcile_task.delay(
        workspaces=request.workspaces,
        dry_run=request.dry_run,
    )

    return SlackUsergroupsTaskResponse(
        task_id=task.id,
        status="queued",
        status_url=f"/api/v1/integrations/slack-usergroups/reconcile/{task.id}",
    )


@router.get(
    "/reconcile/{task_id}",
    response_model=SlackUsergroupsTaskResult,
)
async def get_reconcile_result(
    task_id: str,
    current_user: UserDep,
    timeout: int = Query(default=60, ge=1, le=300),
) -> SlackUsergroupsTaskResult:
    """Retrieve reconciliation result (blocks until complete or timeout)."""

    # Poll task status with timeout
    start_time = time.time()
    poll_interval = 0.5  # 500ms

    while time.time() - start_time < timeout:
        result = task result(task_id)

        if result.ready():
            if result.successful():
                return result.get()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Task failed: {result.info}",
            )

        await asyncio.sleep(poll_interval)

    # Timeout reached
    raise HTTPException(
        status_code=status.HTTP_408_REQUEST_TIMEOUT,
        detail=f"Task not completed within {timeout} seconds",
    )
```

### Client Implementation

```python
def reconcile(
    desired_state: list[SlackWorkspace],
    dry_run: bool,
    wait_for_result: bool = True,
    timeout: int = 60,
):
    """Reconcile Slack usergroups via qontract-api."""

    # Always queue task
    response = api_client.post("/reconcile", json={
        "workspaces": desired_state,
        "dry_run": dry_run,
    })

    task_id = response["task_id"]

    if not wait_for_result:
        # Fire-and-forget
        return task_id

    # Wait for result (blocking GET)
    result = api_client.get(
        response["status_url"],
        params={"timeout": timeout},
    )

    return result
```

## Configuration

Task timeout must align with OpenShift route timeout to prevent gateway timeouts.

### Environment Variables

- `QAPI_API_TASK_MAX_TIMEOUT`: Maximum allowed timeout in seconds (default: 300)
  - Must be less than OpenShift route timeout
  - Example: If route timeout is 5 minutes, set to 290 seconds
- `QAPI_API_TASK_DEFAULT_TIMEOUT`: Default timeout when not specified (default: None)
  - None = non-blocking by default
  - Set to enable blocking by default (e.g., 60 for MR jobs)

### Example Configuration

```bash
# OpenShift route has 5min timeout
QAPI_API_TASK_MAX_TIMEOUT=290  # Max timeout slightly less than route
QAPI_API_TASK_DEFAULT_TIMEOUT=  # Empty = non-blocking default
```

## References

- Related: [ADR-002](ADR-002-client-side-graphql-fetching.md) - Client-side GraphQL fetching
- Implementation: Router in [qontract_api/integrations/slack_usergroups/router.py](qontract_api/integrations/slack_usergroups/router.py)
- Task utilities: [qontract_api/tasks/_utils.py](qontract_api/tasks/_utils.py)
- Models: [qontract_api/integrations/slack_usergroups/models.py](qontract_api/integrations/slack_usergroups/models.py)
- Status enum: [qontract_api/models.py](qontract_api/models.py)

---

## Notes

This ADR supersedes the original ADR-003 which used an `execution_mode` parameter. The async-only pattern is more RESTful, simpler to implement, and provides better separation between task creation (POST) and result retrieval (GET).

The blocking GET pattern eliminates client-side polling complexity while maintaining the flexibility of async execution. Clients that need results (MR validation) can block, while fire-and-forget clients (some production runs) can skip the GET entirely.
