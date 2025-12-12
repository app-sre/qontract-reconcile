# ADR-002: Client-Side GraphQL Fetching Only

**Status:** Accepted
**Date:** 2025-11-14
**Authors:** cassing
**Supersedes:** N/A
**Superseded by:** N/A

## Context

The qontract-reconcile ecosystem consists of two main components:

- **qontract-server**: GraphQL API serving desired state from git repository (app-interface)
- **qontract-api**: REST API for reconciliation (fetches current state, calculates diff, applies changes)

A fundamental question arises: **Who should fetch the desired state from qontract-server?**

### Current State

Traditional qontract-reconcile integrations:

1. Integration fetches desired_state from qontract-server (GraphQL)
2. Integration fetches current_state from external system (Slack, AWS, etc.)
3. Integration calculates diff and applies changes

### Requirements

- **MR validation**: GitLab MR jobs must validate changes before merge
- **Production runs**: Scheduled jobs apply changes to external systems
- **Statelessness**: API should remain stateless
- **Clear separation**: Avoid mixing concerns (GraphQL vs external APIs)

## Decision

**The client (integration/MR job) fetches desired_state from qontract-server and sends it to qontract-api. The API ONLY fetches current_state from external systems.**

### Client Workflow

```text
Client (reconcile/slack_usergroups_api.py)
  │
  ├─> 1. Fetch desired_state from qontract-server (GraphQL)
  │      query { ... slack usergroups ... }
  │
  └─> 2. Send desired_state to qontract-api (REST)
       POST /api/v1/integrations/slack-usergroups/reconcile
       {
         "desired_state": {...},
         "dry_run": true
       }

qontract-api
  │
  ├─> 3. Fetch current_state from Slack API
  │      GET /usergroups.list, /users.list, etc.
  │
  ├─> 4. Calculate diff (desired vs current)
  │
  └─> 5. Return actions to client
       {
         "actions": [{"action_type": "update_users", ...}],
         "applied_count": 0
       }
```

### API Responsibilities

**qontract-api is responsible for:**

- Fetching current_state from external systems (Slack, AWS, GitHub, etc.)
- Calculating diff between desired_state (provided by client) and current_state
- Applying changes to external systems (if not dry_run)
- Caching current_state (to reduce external API calls)
- Rate limiting external API calls

**qontract-api is NOT responsible for:**

- Fetching desired_state from qontract-server
- GraphQL queries
- App-interface schema knowledge

**Client is responsible for:**

- Fetching desired_state from qontract-server (GraphQL) and qontract-api (REST)
- Formatting desired_state according to API schema
- Sending reconciliation request to qontract-api
- Logging/displaying actions returned by API

## Alternatives Considered

### Alternative 1: API Fetches GraphQL Directly (Rejected)

qontract-api queries qontract-server for desired_state.

**Pros:**

- Client code simpler (just call API)
- One less step for client

**Cons:**

- API needs GraphQL client dependency
- API must know app-interface schema
- Tight coupling between qontract-api and qontract-server
- API becomes stateful (needs to track which query to run)
- Cannot validate MR changes (API would fetch merged data, not MR changes)
- Harder to test (need mock GraphQL server)

### Alternative 2: Hybrid Approach (Rejected)

Client can optionally send desired_state OR API fetches it.

**Pros:**

- Flexible

**Cons:**

- Confusing: two ways to do same thing
- More complexity in API
- Unclear which mode to use when
- Still has all cons of Alternative 1

### Alternative 3: Client-Side GraphQL Only (Selected)

Client always fetches desired_state, API only fetches current_state.

**Pros:**

- Clear separation of concerns
- API remains stateless
- No GraphQL dependency in API
- Works for MR validation (client fetches MR branch data)
- Easier to test (just mock external APIs, not GraphQL)
- Client controls what data is sent
- Simpler API surface

**Cons:**

- Client must fetch GraphQL first
  - **Mitigation:** Existing integrations already do this
  - Not a significant burden

## Consequences

### Positive

1. **Clear separation of concerns**: API focuses on reconciliation, not data fetching
2. **Stateless API**: No need to track which GraphQL queries to run
3. **Works for MR validation**: Client fetches from MR branch, API validates
4. **Simpler dependencies**: No GraphQL client in qontract-api
5. **Easier testing**: Only need to mock external APIs (Slack, AWS)
6. **Flexible client**: Client can transform/filter data before sending to API
7. **No schema coupling**: API doesn't need to know app-interface schema

### Negative

1. **Two-step process**: Client must fetch GraphQL, then call API
   - **Mitigation:** Existing integrations already do this
   - Not a significant burden
   - Can be encapsulated in client library

2. **Network overhead**: Two requests instead of one
   - **Mitigation:** GraphQL query is fast (qontract-server is in same cluster)
   - Minimal impact

## Implementation Guidelines

### Client Implementation

```python
# reconcile/slack_usergroups_api.py

def run(dry_run: bool):
    # 1. Fetch desired state from qontract-server
    gqlapi = gql.get_api()
    apps = gqlapi.query(query)  # GraphQL query

    # 2. Transform to API schema
    desired_state = transform_to_api_schema(apps)

    # 3. Call qontract-api
    response = api_client.post(
        "/api/v1/integrations/slack-usergroups/reconcile",
        json={"desired_state": desired_state, "dry_run": dry_run}
    )

    # 4. Process response
    for action in response["actions"]:
        logging.info(f"Action: {action}")
```

### API Implementation

```python
# qontract_api/integrations/slack_usergroups/router.py

@router.post("/reconcile")
async def reconcile(request: ReconcileRequest):
    # desired_state already provided by client (from GraphQL)
    # API only fetches current_state from Slack

    service = SlackUsergroupsService(...)
    return await service.reconcile(
        desired_state=request.desired_state,
        dry_run=request.dry_run
    )
```

### Testing

**Client tests**: Mock qontract-server GraphQL API and qontract-api REST API

**API tests**: Only mock external APIs (Slack, AWS) - no GraphQL mocking needed

## References

- Related: qontract-server GraphQL API
