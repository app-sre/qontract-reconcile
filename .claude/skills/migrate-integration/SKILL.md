---
name: migrate-integration
description: Migrate a reconcile/ integration to the qontract-api architecture. Use this skill when someone wants to rewrite, migrate, or port an existing reconcile integration to the API-based pattern, or when they mention creating a new qontract-api integration based on an existing one. Also triggers on mentions of "migrate to api", "rewrite for qontract-api", "create api integration", or "port integration". This is the primary skill for any reconcile-to-api migration work.
---

# Migrate Integration to qontract-api

Guide the migration of an existing `reconcile/` integration to the qontract-api architecture. This skill analyzes the existing integration, creates a migration plan, and generates all required code in phases.

Two successful migrations serve as reference implementations:

- `slack_usergroups` -> `slack_usergroups_api`
- `glitchtip_project_alerts` -> `glitchtip_project_alerts_api`

## Input

Integration name in kebab-case (e.g., `aws-account-manager`). If not provided, ask for it.

## General

The discovery phase is critical to ensure a smooth migration. Never skip it, and never start coding before the plan is confirmed by the user.

## Migration Plans

Migration plans are stored in `.claude/skills/migrate-integration/plans/<name>.md`. These persist across sessions and allow resuming work after context clears.

**Before starting any phase**, always read the migration plan for the integration to understand current status, decisions, and resumption context. Update the plan's status and checkboxes as you complete tasks.

**Between phases**, the user may clear context (`/clear`). Each phase in the plan includes a "Resumption context" section that tells you what files to read to rebuild context for that phase.

## Agent Teams

Use agent teams throughout the migration to parallelize work, coordinate complex tasks, and enable deep thinking on architectural decisions. Don't hesitate to spin up multiple agents — they are cheap and fast.

### When to use agent teams

- **Phase 0 (Discovery)**: Always. Launch parallel agents to explore different aspects simultaneously:
  - Agent 1: Deep dive into the existing integration code (all source files, data models, state management)
  - Agent 2: Explore existing qontract-api patterns (reference implementations, task infrastructure, events)
  - Agent 3: Explore ADRs, infrastructure, and existing utilities in `qontract_utils/`
  - Agent 4 (deep thinker): If the integration has complex architectural challenges (state machines, multi-step workflows, novel patterns), dedicate an agent to think deeply about the design. Give it a `Plan` subagent type and let it explore the codebase AND reason about the solution.

- **Implementation phases**: When a phase has independent sub-tasks (e.g., creating models.py, service.py, and router.py), launch agents in parallel for each file. One agent can write the service while another writes the router.

- **Complex decisions**: When facing a non-trivial architectural decision, launch a dedicated `Plan` agent to think it through. Give it full context and ask it to explore alternatives, trade-offs, and propose a detailed design.

### Agent team guidelines

- **Background agents**: Use `run_in_background: true` for discovery/research agents so they work in parallel. Wait for all to complete before synthesizing.
- **Deep thinking agents**: Use `Plan` subagent type when you want an agent to reason deeply about architecture, not just search for code.
- **Explore agents**: Use `Explore` subagent type for thorough codebase searches. Specify thoroughness: "very thorough" for discovery phases.
- **Don't duplicate work**: If an agent is exploring a topic, don't search for the same things yourself. Trust the agent's results.
- **Synthesize results**: After all agents report back, compile their findings into a coherent plan. Ask the user questions interactively (one at a time, not as a text dump).

## Stateful vs Stateless Integrations

Some integrations are **stateless** (like slack-usergroups, glitchtip): each reconciliation run diffs desired vs current state and applies changes atomically. Others are **stateful** (like aws-account-manager): operations span multiple reconciliation runs with async external operations.

### Identifying Stateful Integrations

Look for these patterns in the existing integration:

- S3/Redis/file-based state tracking across runs
- Async operations that require polling (e.g., AWS CreateAccount -> poll for completion)
- Multi-step sequential workflows (step N depends on step N-1's result)
- `AbortStateTransactionError` or similar "retry next run" patterns

### Handling Stateful Integrations

Stateful integrations use the **Workflow Framework** (`qontract_api/qontract_api/workflow/`). This provides:

- **WorkflowStore**: Redis-backed persistence for workflow state (key: `workflow:<integration>:<workflow_id>`)
- **WorkflowExecutor**: Sequential step execution with resume-from-last-incomplete support
- **Management endpoints**: List, inspect, reset, and delete workflows via REST API
- **Step handlers**: Per-step functions returning `StepResult` with status + context updates

Key patterns:

- Steps return `StepStatus.IN_PROGRESS` for async operations (executor stops, resumes next run)
- Steps return `StepStatus.FAILED` for errors (operator can reset via API)
- `context` dict passes serializable data between steps (request IDs, account UIDs, etc.)
- Non-serializable deps (API clients) are injected via closures, NOT stored in context
- Distributed locking prevents concurrent modifications to the same workflow

Stateful integrations typically need **two endpoints**:

1. A stateful workflow endpoint (e.g., `/create`) for multi-step operations
2. A stateless diff endpoint (e.g., `/reconcile`) for ongoing reconciliation of existing resources

## Phase 0: Discovery & Analysis

1. **Find the existing integration.** Search for source files:
   - `reconcile/<name>.py` or `reconcile/<name>/` directory
   - Related test files in `tests/`
   - GraphQL queries in `reconcile/gql_definitions/`
   - Any shared utilities the integration uses from `reconcile/utils/`
   - **Existing API clients in `qontract_utils/qontract_utils/`** — search thoroughly for domain-related modules (e.g., `aws_api_typed/`, `slack/`, `glitchtip/`)
   - **Existing domain layers in `qontract_api/qontract_api/`** — check if a domain layer already exists (e.g., `slack/`, `glitchtip/`)
   - **Existing external endpoints in `qontract_api/qontract_api/external/`**

2. **Show discovered files** and ask user to confirm or add missing ones.

3. **Analyze the existing integration** to understand:
   - What external APIs it calls (Slack, AWS, GitHub, PagerDuty, etc.)
   - What the `run()` / `desired_state()` / `current_state()` functions do
   - What reconciliation actions it performs (create, update, delete)
   - What secrets/credentials it needs
   - What data models it uses (dicts vs dataclasses vs pydantic)
   - Whether it supports sharding, early-exit, or other patterns
   - Whether it is stateful or stateless (see "Stateful vs Stateless Integrations" section)
   - What shared utilities from `reconcile/utils/` it depends on (these can NOT be imported in qontract-api per ADR-007 — equivalent functionality must exist or be created in `qontract_utils/`)
   - **What external data the client needs for desired state compilation** (e.g., PagerDuty schedules, VCS OWNERS files, AWS resource lists). This determines whether external endpoints are needed (Phase 3).

4. **Save the migration plan** to `.claude/skills/migrate-integration/plans/<name>.md`:
   - All discovered source files and their purpose
   - Key architectural decisions (action types, model structure, stateful/stateless, endpoint structure)
   - Files to create per phase with status tracking (checkboxes)
   - Each phase gets a "Resumption context" section explaining what to read after a `/clear`
   - Phase dependency graph (which phases can run in parallel, which are prerequisites)
   - What goes where: `qontract_utils/` vs `qontract_api/<domain>/` vs `qontract_api/integrations/` vs `qontract_api/external/`

5. **Present the plan to the user** and ask questions interactively (one at a time). Wait for user confirmation before proceeding.

6. **Old integration**: Do NOT modify or delete the old integration in `reconcile/`. Inform the user that they can roll out the new `_api` integration via unleash feature toggles alongside the old one, and decommission the old one once the new one is verified in production.

## Phase 1: Shared Utilities (qontract_utils/)

Following ADR-007 (no reconcile/ imports in qontract-api) and ADR-014 (three-layer architecture).

`qontract_utils/` contains **only** pure API client abstractions (Layer 1) and generic utilities. Everything here **must be synchronous** because it is used by Celery workers which run sync code.

1. **IMPORTANT: Check for existing API clients first.** Before creating anything, thoroughly search `qontract_utils/qontract_utils/` for existing clients:
   - Search for the domain name (e.g., `aws`, `slack`, `glitchtip`, `pagerduty`)
   - Check both exact matches and related names (e.g., `aws_api_typed/` not just `aws/`)
   - Use `Glob` on `qontract_utils/qontract_utils/**/*.py` and scan for relevant modules
   - Existing clients to be aware of:
     - `qontract_utils/qontract_utils/aws_api_typed/` - AWS APIs (Organizations, IAM, STS, S3, Support, Account, Service Quotas, etc.)
     - `qontract_utils/qontract_utils/slack/` - Slack API
     - `qontract_utils/qontract_utils/glitchtip/` - Glitchtip API
     - `qontract_utils/qontract_utils/pagerduty/` - PagerDuty API
   - If a client exists, check if it covers all needed methods. Only extend, never duplicate.

2. **Layer 1 - Pure API Client** (`qontract_utils/<domain>/api.py`):
   - Thin synchronous wrapper around the external API (REST/GraphQL calls)
   - No business logic, no caching, no state
   - Uses `@with_hooks` and `@invoke_with_hooks()` decorators for metrics/retries (ADR-006)
   - **All methods must be synchronous** - Celery workers are sync-only
   - Example reference: `qontract_utils/slack/api.py`, `qontract_utils/glitchtip/api.py`

3. **Create tests** for new API client classes in `tests/qontract_utils/`.

**Important**: Workspace clients (Layer 2) do NOT go in `qontract_utils/`. They belong in `qontract_api/` (see Phase 2).

## Phase 2: Server-Side Integration (qontract_api/)

### Domain Layer (qontract_api/qontract_api/<domain>/)

**Check if a domain layer already exists** before creating a new one. Search `qontract_api/qontract_api/` for existing domain directories (e.g., `slack/`, `glitchtip/`). If one exists for your domain, extend it rather than creating a duplicate.

A domain layer in `qontract_api/<domain>/` is needed when the domain has **shared infrastructure** (workspace client, factory) used by multiple integrations or external endpoints. If only one integration uses the domain models, put `domain.py` inside the integration folder instead (see Integration Files below).

Create `qontract_api/qontract_api/<domain>/`:

- **`domain.py`** - Shared domain models (Pydantic, frozen=True). These model the external system's concepts (workspaces, usergroups, instances, projects, etc.). Only create this file in the domain layer if multiple integrations share these models. If only one integration uses them, put `domain.py` inside the integration folder instead (see below).
- **`<domain>_client_factory.py`** - Factory for creating workspace clients (ADR-017). Resolves secrets via SecretManager, creates API client + workspace client with proper configuration.
- **`workspace_client.py`** (Layer 2) - Caching layer on top of the pure API client:
  - In-memory + Redis caching via `CacheBackend`
  - Distributed locking for thread-safety
  - Computed/derived data helpers
  - **Synchronous** (runs in Celery worker context)
  - Example reference: `qontract_api/qontract_api/slack/slack_workspace_client.py`

Reference: `qontract_api/qontract_api/slack/`, `qontract_api/qontract_api/glitchtip/`

### Integration Files (qontract_api/qontract_api/integrations/<name_underscore>/)

#### domain.py (desired-state models)

Following ADR-012 (typed Pydantic models):

- Contains desired-state Pydantic models used by the reconciliation logic (instances, organizations, projects, alerts, etc.)
- Models represent **what the system wants to reconcile** — no `pk` fields, may include validators
- All models `frozen=True` for immutability
- Place here when the domain models are **only used by this one integration**. If shared with other integrations, place in `qontract_api/<domain>/domain.py` instead and import from there.

Reference: `qontract_api/qontract_api/integrations/glitchtip_project_alerts/domain.py`

#### schemas.py (API contract)

Following ADR-012 (typed Pydantic models):

- **Request model**: `<Name>ReconcileRequest(BaseModel, frozen=True)` with `dry_run: bool = True`
- **Action models**: Discriminated union with `action_type` field as `Literal`. One model per action type (create, update, delete, etc.)
- **Task result**: `<Name>TaskResult(TaskResult, frozen=True)` with `actions: list[<Name>Action]`
- **Task response**: `<Name>TaskResponse(BaseModel, frozen=True)` with `id`, `status`, `status_url`
- All models `frozen=True` for immutability
- Sort list fields via `field_validator` for deterministic output

Reference: `qontract_api/qontract_api/integrations/slack_usergroups/schemas.py`

#### service.py

Following ADR-011 (dependency injection) and ADR-014 (three-layer architecture):

- **Class**: `<Name>Service` with constructor injection of `cache`, `secret_manager`, `settings`, and client factories
- **`reconcile()` method**: Main entry point accepting desired state + `dry_run`
  1. For each resource group: create client via factory, fetch current state, calculate diff
  2. Use `qontract_utils.differ.diff_iterables()` for diffing
  3. Generate typed action models
  4. Execute actions if `dry_run=False` (using `match/case` on action type)
  5. Return `<Name>TaskResult` with status, actions, applied_count, errors
- **Error handling**: Try/except per resource group and per action. Collect errors, continue processing.
- Static helper methods for `_calculate_actions()` and `_execute_action()`

Reference: `qontract_api/qontract_api/integrations/slack_usergroups/service.py`

#### router.py

Following ADR-003 (async-only API with blocking GET):

- **POST `/reconcile`** (HTTP 202 Accepted):
  - Accepts `<Name>ReconcileRequest`
  - Requires JWT auth (`UserDep`)
  - Queues Celery task via `apply_async()`
  - Returns `<Name>TaskResponse` with task_id and status_url

- **GET `/reconcile/{task_id}`** (blocking/non-blocking):
  - Optional `timeout` query param (1-300 seconds)
  - Uses `wait_for_task_completion()` helper
  - Returns `<Name>TaskResult`

- Router prefix: `/<name-kebab>` (e.g., `/aws-account-manager`)

Reference: `qontract_api/qontract_api/integrations/slack_usergroups/router.py`

#### tasks.py

Following ADR-018 (event-driven communication):

- **Celery task** with `@celery_app.task(bind=True, name="<name-kebab>.reconcile", acks_late=True)`
- **Deduplication** via `@deduplicated_task(lock_key_fn=generate_lock_key, timeout=600)`
- Lock key from resource identifiers (workspace names, instance names, etc.)
- Create service with injected dependencies (`get_cache()`, `get_secret_manager()`, `get_event_manager()`)
- **Event publishing** for applied actions (non-dry-run): publish `Event` per action to Redis Streams
- Error handling: catch exceptions, return failed `<Name>TaskResult`

Reference: `qontract_api/qontract_api/integrations/slack_usergroups/tasks.py`

#### `__init__.py`

Empty file or re-exports.

### Infrastructure Registration

1. **Register router** in `qontract_api/qontract_api/routers/integrations.py`:

   ```python
   integrations_router.include_router(<name>_router.router)
   ```

2. **Register Celery task** in `qontract_api/qontract_api/tasks/__init__.py`:
   Add module path to `include` list in `Celery()` config.

3. **Add settings** to `qontract_api/qontract_api/config.py` if needed (cache TTLs, timeouts, etc.)

4. **Regenerate the API client** after creating server-side routers (see Phase 4 prerequisites).

## Phase 3: External Endpoints (if needed)

**This phase is required when the client-side integration needs data from external services to compile its desired state.** For example, `slack_usergroups_api` needs PagerDuty schedule users and VCS repo OWNERS to build the complete desired state before sending it to the reconciliation endpoint.

Following ADR-013 (centralize external API calls): the client MUST NOT call external APIs directly. Instead, qontract-api provides external endpoints that the client calls.

Check if the old integration fetches data from external services during desired state compilation. Common patterns:

- PagerDuty schedules/escalation policies for on-call users
- VCS/GitHub/GitLab for OWNERS file data
- AWS for resource listings
- Any other external API calls in the old `desired_state()` / `get_desired_state()` / `run()`

If external endpoints are needed, create `qontract_api/qontract_api/external/<service>/`:

- **`schemas.py`** - Request/response models for the external endpoint
- **`router.py`** - FastAPI endpoint (typically GET with query params for secret references)
- **`<service>_workspace_client.py`** - Caching wrapper for the external API client
- **`<service>_factory.py`** - Factory to create workspace clients

Register external routers in `qontract_api/qontract_api/routers/external.py`.

**Check if external endpoints already exist** before creating new ones. Existing externals:

- `qontract_api/qontract_api/external/pagerduty/` - PagerDuty schedule/escalation policy users
- `qontract_api/qontract_api/external/vcs/` - VCS repo OWNERS
- `qontract_api/qontract_api/external/slack/` - Slack API proxying

Reference: `qontract_api/qontract_api/external/pagerduty/`, `qontract_api/qontract_api/external/vcs/`

### Auto-Generated Client

After creating server-side routers (integration + external), regenerate the API client (see Phase 4 prerequisites).

## Phase 4: Client-Side Integration (reconcile/)

> **Prerequisite:** The API client must be regenerated before starting this phase. Run after Phase 2, and again after Phase 3 if external endpoints were added:
> ```bash
> cd qontract_api && make generate-openapi-spec
> cd qontract_api_client && make generate-client
> ```
> This creates typed Python client functions matching all new endpoints.

Following ADR-008 (QontractReconcileApiIntegration pattern).

The client-side integration is responsible for **all desired state computation**. It queries App-Interface via GraphQL, enriches the data with external service data (via qontract-api external endpoints from Phase 3), and sends the complete desired state to the reconciliation endpoint.

Create `reconcile/<name_underscore>_api.py` (single file) or `reconcile/<name_underscore>_api/` (package with `integration.py`):

- **Class**: `<Name>Integration(QontractReconcileApiIntegration[<Name>IntegrationParams])`
- **Params**: `<Name>IntegrationParams(PydanticRunParams)` with optional filter parameters
- **`async_run(dry_run: bool)`**: Main entry point (async, not sync)

### Desired State Compilation (client-side responsibility)

The client compiles the complete desired state. This typically involves:

1. **Query App-Interface GraphQL** for configuration data (permissions, roles, resources, clusters, users, etc.)
2. **Enrich with external data** (if needed) by calling qontract-api external endpoints:
   - PagerDuty users: `get_pagerduty_schedule_users()`, `get_pagerduty_escalation_policy_users()`
   - VCS OWNERS: `get_repo_owners()`
   - Use `asyncio.gather()` for parallel external calls
3. **Compile** the desired state from all sources into the request model
4. **Send** to qontract-api reconciliation endpoint

Reference for complex desired state: `reconcile/slack_usergroups_api.py` - compiles users from 5 sources (roles, schedules, git OWNERS, PagerDuty, cluster access), all happening client-side before calling the API.

### Task Handling

- Call qontract-api via auto-generated client: `reconcile_<name>(client=self.qontract_api_client, body=request)`
- **Dry-run**: wait for task completion via `<name>_task_status(client, task_id, timeout=300)`
- **Non-dry-run**: fire-and-forget (task completes in background, events published via events framework)
- Log actions using `match/case` on action types
- Exit with error if task result contains errors

Reference: `reconcile/slack_usergroups_api.py`, `reconcile/glitchtip_project_alerts_api/integration.py`

### Integration Registration

The new `_api` integration must be registered in `reconcile/cli.py`. Search for existing `_api` integrations (e.g., `slack_usergroups_api` or `glitchtip_project_alerts_api`) in that file and follow the same pattern.

## Phase 5: Tests

Create comprehensive tests following existing patterns:

1. **Server-side tests** in `tests/qontract_api/integrations/<name>/`:
   - `test_models.py` - Model validation, serialization, frozen behavior
   - `test_service.py` - Reconciliation logic, diff calculation, action generation, error handling
   - `test_router.py` - Endpoint behavior, auth, task queuing, status retrieval
   - `test_tasks.py` - Task execution, deduplication, event publishing

2. **Client-side tests** in `tests/test_<name>_api.py` or `tests/<name>_api/`:
   - Desired state compilation from all sources
   - External API call handling
   - API request construction
   - Task result handling

3. **Utility tests** in `tests/qontract_utils/<domain>/`:
   - API client methods (Layer 1)

4. **Domain tests** in `tests/qontract_api/<domain>/`:
   - Workspace client caching behavior (Layer 2)
   - Factory tests

Use `pytest`, `@pytest.fixture`, `@pytest.mark.parametrize`. Mock external API calls. Test both dry-run and non-dry-run paths.

## Phase 6: Documentation & Skill Update

### Integration Documentation

After all code is generated, invoke the `document-api-integration` skill to create `docs/integrations/<name>.md` following the standard template.

### Update This Skill

After completing the migration, update **this SKILL.md** with any new knowledge gained during the process. This keeps the skill accurate for future migrations. Specifically check and update:

- **Existing API clients list** (Phase 1): If new API clients were created or existing ones extended in `qontract_utils/`, add them to the known clients list.
- **Existing external endpoints list** (Phase 3): If new external endpoints were created, add them to the known externals list.
- **New ADRs**: If new ADRs were written (e.g., for workflow framework, new patterns), reference them in the relevant phase descriptions.
- **New architectural patterns**: If the migration introduced new patterns (e.g., workflow framework for stateful integrations), document them in the appropriate section.
- **Reference implementations**: Add the completed migration as a reference implementation alongside slack_usergroups and glitchtip at the top of this file.
- **Gotchas and lessons learned**: If any unexpected issues came up, add them to the Key Rules section or relevant phase.

## Output Format

Show progress after each phase:

```
## Migration: <name>

Phase 0: Discovery & Analysis
  Found 5 source files, 3 action types, 2 external APIs

Phase 1: Shared Utilities (qontract_utils/)
  Created qontract_utils/<domain>/api.py

Phase 2: Server-Side (qontract_api/)
  Created qontract_api/<domain>/domain.py, workspace_client.py, factory.py
  Created qontract_api/integrations/<name>/domain.py, schemas.py
  Created qontract_api/integrations/<name>/service.py
  Created qontract_api/integrations/<name>/router.py
  Created qontract_api/integrations/<name>/tasks.py

Phase 3: External Endpoints
  Reusing existing pagerduty external endpoints
  Created qontract_api/external/<service>/router.py

Phase 4: Client-Side (reconcile/)
  Created reconcile/<name>_api.py

Phase 5: Tests
  Created 10 test files

Phase 6: Documentation
  Created docs/integrations/<name>.md
```

## Verification & Commit

After completing each implementation phase, run verification and commit before moving on:

```bash
make format               # Auto-format code
make linter-test          # Lint checks
make types-test           # MyPy strict mode
make unittest             # Unit tests (or pytest on specific test files)
```

Fix any issues, then commit with a message following this pattern:

```bash
git add <relevant files>
git commit -m "<integration-name>-api: phase N - <short description>"
```

Examples:
- `aws-account-manager-api: phase 1 - shared utilities`
- `aws-account-manager-api: phase 2 - server-side integration`
- `aws-account-manager-api: phase 3 - external endpoints`
- `aws-account-manager-api: phase 4 - client-side integration`
- `aws-account-manager-api: phase 5 - tests`
- `aws-account-manager-api: phase 6 - documentation`

Update the migration plan with the phase status after committing.

## Phase Dependencies

Phases have dependencies. Document these in the migration plan so phases can be parallelized where possible:

- **Phase 1** (shared utils) is always a prerequisite for Phase 2 (server-side)
- **Phase 2** (server-side) is a prerequisite for Phase 3 (external endpoints) and Phase 4 (client-side)
- **Phase 5** (tests) can partially overlap with implementation phases (write tests as you go)
- **Sub-phases** (e.g., 1a, 1b, 1.5) may or may not depend on each other — analyze per migration and document in the plan

## Key Rules

- **Never import from `reconcile/` in qontract-api code** (ADR-007)
- **`qontract_utils/` is sync-only** - used by Celery workers. Only Layer 1 API clients go here.
- **Workspace clients (Layer 2) belong in `qontract_api/`**, not `qontract_utils/`
- **Domain models in integration folder (`domain.py`) when only used by one integration**; move to `qontract_api/<domain>/domain.py` only when shared across multiple integrations or needed by the workspace client
- **Factories and workspace clients always in `qontract_api/<domain>/`** (shared infrastructure)
- **Integration files use `domain.py` + `schemas.py`**, not `models.py`: `domain.py` = desired-state reconciliation models, `schemas.py` = API contract (request/response/action models)
- **External endpoint files use `schemas.py`**, not `models.py`: API request/response models
- **All models are Pydantic with `frozen=True`** (ADR-012)
- **All dependencies injected via constructor** (ADR-011)
- **`dry_run` always defaults to `True`** - safety first
- **Use `match/case`** for action dispatch
- **Use `qontract_utils.differ.diff_iterables()`** for diffing
- **Client compiles ALL desired state** - GraphQL + external data enrichment happens in reconcile client
- **External API calls only via qontract-api external endpoints** (ADR-013) - client calls these, never external APIs directly
- **Don't touch the old integration** - leave `reconcile/<name>/` as-is. The user can roll out the new `_api` integration via unleash feature toggles and decommission the old one later.
- Read existing reference implementations before generating code - adapt patterns, don't copy blindly
- Read all relevant ADRs from `docs/adr/` before starting
