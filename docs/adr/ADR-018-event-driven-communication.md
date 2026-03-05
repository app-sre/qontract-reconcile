# ADR-018: Event-Driven Communication Pattern

**Status:** Accepted
**Date:** 2026-02-10
**Authors:** cassing

## Context

qontract-api performs actions on external systems (e.g., updating Slack usergroup members) that other systems need to be notified about. Currently there is no mechanism for cross-system event notification between qontract-api and reconcile integrations.

- qontract-api celery tasks execute reconciliation actions but results are only stored as task results
- There is no way for reconcile integrations to react to actions performed by qontract-api
- Future use cases require audit logging, notification chains, and event-driven workflows
- The solution must support multiple consumers and be extensible to new event types

## Decision

Use [faststream](https://faststream.ag2.ai/) with [CloudEvents](https://cloudevents.io/) for event-driven communication between qontract-api (producer) and subscriber processes (consumers). The shared event model and synchronous publishing wrapper live in `qontract_utils`. The subscriber runs as a separate ASGI process via faststream's `AsgiFastStream`.

### Key Points

- **CloudEvents standard** -- the `Event` model extends `cloudevents.pydantic.v2.event.CloudEvent`, providing an industry-standard, self-describing event envelope (`specversion`, `type`, `source`, `id`, `time`, `datacontenttype`, `data`)
- **faststream as messaging framework** -- handles Redis broker connections, message serialization/deserialization, subscriber registration via decorators, and AsyncAPI specification generation
- **Synchronous publisher** (`qontract_utils.events.RedisBroker`) -- wraps faststream's async `RedisBroker` in a sync context manager so that celery workers (sync) can publish events without async overhead
- **Subscriber as ASGI app** (`qontract_api.subscriber`) -- runs as a separate uvicorn process with health check endpoints and auto-generated AsyncAPI documentation
- **`EventManager`** (`qontract_api.event_manager`) -- encapsulates publishing with fire-and-forget semantics: failures are logged but never propagate to the producer task
- **Feature-flagged** -- event publishing is controlled via `QAPI_EVENTS__ENABLED` (default: `true`) and the channel name via `QAPI_EVENTS__CHANNEL` (default: `"main"`)

## Alternatives Considered

### Alternative 1: DIY Redis Streams with Protocol Abstraction

Custom `EventPublisher`/`EventConsumer` protocols with factory functions, Redis Streams backend (XADD/XREADGROUP/XACK), and manual consumer group management.

**Pros:**

- Full control over implementation details
- No external framework dependency

**Cons:**

- Significant boilerplate: custom protocols, factories, consumer group management, serialization
- No standard event format -- custom schema requires documentation and versioning
- No auto-generated API documentation
- Consumer lifecycle (pending messages, acknowledgment, group creation) must be hand-coded

### Alternative 2: AWS SNS + SQS

SNS for publishing (fan-out), SQS for consuming (durable queues).

**Pros:**

- Native fan-out: multiple SQS queues subscribe to one topic
- Managed infrastructure with high availability

**Cons:**

- App-interface (external-resources) doesn't support SNS with SQS subscriptions
- SNS wraps messages in an envelope that must be unwrapped
- AWS credentials must be managed separately

### Alternative 3: faststream with CloudEvents (Selected)

faststream handles the messaging infrastructure (broker connections, serialization, subscriber lifecycle). CloudEvents provides the standardized event envelope.

**Pros:**

- Minimal boilerplate: decorator-based subscriber registration, automatic serialization
- Industry-standard event format (CloudEvents 1.0) -- no custom schema to maintain
- Auto-generated AsyncAPI documentation at `/docs/asyncapi`
- Built-in health check endpoints for Kubernetes readiness/liveness
- Sync publisher wrapper is thin (~40 lines) -- all heavy lifting delegated to faststream
- Uses existing Redis infrastructure -- no additional setup needed

**Cons:**

- External framework dependency (faststream)
- Redis is a single point of failure (unlike managed SNS/SQS)

## Consequences

### Positive

- No additional infrastructure required -- uses existing Redis
- Decoupled communication between qontract-api and subscribers
- CloudEvents standard enables interoperability with external systems and tooling
- AsyncAPI documentation auto-generated for service discovery
- Subscriber runs as independent process -- can be scaled separately
- Minimal code to maintain: the sync publisher wrapper and event model are ~50 lines total

### Negative

- Redis as single point of failure
  - **Mitigation:** Redis is already critical infrastructure for caching; adding events doesn't change the risk profile
- External dependency on faststream
  - **Mitigation:** The sync publisher wrapper isolates the dependency; only the subscriber directly uses faststream decorators

## Implementation Guidelines

### Event Model

```python
from qontract_utils.events import Event

event = Event(
    source="qontract-api",
    type="qontract-api.slack-usergroups.update_users",
    data={"workspace": "coreos", "usergroup": "team-a", "users": ["alice"]},
    datacontenttype="application/json",
)
```

### Publishing Events (Producer -- Sync)

Use `EventManager` in qontract-api celery tasks:

```python
from qontract_api.event_manager import get_event_manager
from qontract_utils.events import Event

event_manager = get_event_manager()
if event_manager:
    event_manager.publish_event(
        Event(
            source=__name__,
            type=f"qontract-api.slack-usergroups.{action.action_type}",
            data=action.model_dump(mode="json"),
            datacontenttype="application/json",
        )
    )
```

For direct publishing (e.g., scripts or tests):

```python
from qontract_utils.events import Event, RedisBroker

with RedisBroker("redis://localhost:6379") as broker:
    broker.publish(
        Event(
            source="my-script",
            type="test.ping",
            data={"hello": "world"},
            datacontenttype="application/json",
        ),
        channel="main",
    )
```

### Subscribing to Events (Consumer -- Async)

Add handlers in `qontract_api/qontract_api/subscriber/_subscriptions.py`:

```python
from qontract_utils.events import Event

from ._base import broker


@broker.subscriber("main")
async def base_handler(event: Event) -> None:
    print(event)
```

The subscriber runs as a separate process:

```bash
QAPI_START_MODE=subscriber uvicorn qontract_api.subscriber:app
```

### Configuration (qontract-api)

Environment variables (prefix `QAPI_`):

| Variable | Default | Description |
|---|---|---|
| `QAPI_EVENTS__ENABLED` | `true` | Enable/disable event publishing |
| `QAPI_EVENTS__CHANNEL` | `"main"` | Redis channel name for events |
| `QAPI_START_MODE` | `"api"` | Process mode: `api`, `worker`, or `subscriber` |

The Redis connection is reused from the existing cache backend (`cache_broker_url`).

### Checklist

- [ ] Event publishing is behind a feature flag (`QAPI_EVENTS__ENABLED`)
- [ ] Publishing failures do not break the producer (`EventManager` catches all exceptions)
- [ ] Events use CloudEvents format with `source`, `type`, `data`, and `datacontenttype`
- [ ] Event types use dot-separated naming (`qontract-api.integration.action`)
- [ ] New subscribers are registered in `qontract_api/subscriber/_subscriptions.py`

## References

- Related ADRs: ADR-011 (Dependency Injection), ADR-012 (Typed Models), ADR-014 (Three-Layer Architecture)
- Event model and sync broker: `qontract_utils/qontract_utils/events/`
- Subscriber ASGI app: `qontract_api/qontract_api/subscriber/`
- Event manager: `qontract_api/qontract_api/event_manager/`
- [faststream documentation](https://faststream.ag2.ai/)
- [CloudEvents specification](https://cloudevents.io/)
- [AsyncAPI specification](https://www.asyncapi.com/)
