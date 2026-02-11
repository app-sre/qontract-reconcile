# ADR-018: Event-Driven Communication Pattern

**Status:** Accepted
**Date:** 2026-02-10
**Authors:** cassing

## Context

qontract-api performs actions on external systems (e.g., updating Slack usergroup members) that other systems need to be notified about. Currently there is no mechanism for cross-system event notification between qontract-api and reconcile integrations.

- qontract-api celery tasks execute reconciliation actions but results are only stored as task results
- There is no way for reconcile integrations to react to actions performed by qontract-api
- Future use cases require audit logging, notification chains, and event-driven workflows
- The solution must support multiple consumers and be extensible to new backends

## Decision

Use a generic event system with pluggable backends for communication between qontract-api (producer) and reconcile integrations (consumers). The generic API lives in `qontract_utils` with Protocol-based interfaces. The default backend uses Redis Streams (already available via the existing Redis infrastructure). AWS SNS/SQS is available as an alternative backend for future use.

### Key Points

- **Protocol-based interfaces** (`EventPublisher`, `EventConsumer`) enable pluggable backends without code changes in producers/consumers
- **Factory functions** (`create_event_publisher`, `create_event_consumer`) create backend instances -- users never import concrete implementations directly
- **Pydantic `Event` model** with `version`, `event_type`, `source`, `timestamp`, and `payload` fields provides a standardized, versioned event schema
- **Redis Streams as default backend** -- uses the existing Redis infrastructure, no additional infrastructure needed. Consumer groups provide reliable delivery with acknowledgment
- **SNS/SQS available as alternative** -- for fan-out scenarios or when AWS infrastructure is available
- **Fire-and-forget semantics** for publishing: event publishing failures are logged but do not break the producer task
- **At-least-once delivery**: Redis Streams consumer groups guarantee at-least-once delivery; consumers must be idempotent

## Alternatives Considered

### Alternative 1: Redis Pub/Sub

Use Redis Pub/Sub (not Streams) for event messaging.

**Pros:**

- Simple API
- Already available in the stack

**Cons:**

- No durability: messages are lost if no subscriber is listening
- No replay capability for missed events
- No acknowledgment mechanism

### Alternative 2: AWS SNS + SQS

SNS for publishing (fan-out), SQS for consuming (durable queues).

**Pros:**

- Native fan-out: multiple SQS queues subscribe to one topic
- Managed infrastructure with high availability

**Cons:**

- App-interface (external-resources) doesn't support SNS with SQS subscriptions
- SNS wraps messages in an envelope that must be unwrapped
- AWS credentials must be managed separately

### Alternative 3: Redis Streams with Protocol-Based Abstraction (Selected)

Redis Streams for both publishing and consuming, abstracted behind Protocol interfaces. SNS/SQS available as alternative backend.

**Pros:**

- Uses existing Redis infrastructure -- no additional setup needed
- Durable: consumer groups retain messages until acknowledged
- Consumer groups support multiple consumers with load balancing
- Decoupled: producers and consumers only depend on the Protocol interface
- Extensible: SNS/SQS backend already implemented, more can be added via the factory

**Cons:**

- Redis is a single point of failure (unlike managed SNS/SQS)
- No native cross-region replication (unlike SNS)

## Consequences

### Positive

- No additional infrastructure required -- uses existing Redis
- Decoupled communication between qontract-api and reconcile
- Standardized event schema enables audit logging and monitoring
- Protocol-based design allows backend swaps (SNS/SQS, Kafka, etc.)
- Consumer groups provide reliable, acknowledged delivery

### Negative

- Redis as single point of failure
  - **Mitigation:** Redis is already critical infrastructure for caching; adding events doesn't change the risk profile
- At-least-once delivery means consumers must handle duplicate events
  - **Mitigation:** The initial consumer (stdout logger) is inherently idempotent; future consumers must be designed for idempotency

## Implementation Guidelines

### Event Model

```python
from qontract_utils.events.models import Event

event = Event(
    event_type="slack-usergroups.update_users",
    source="qontract-api",
    payload={"workspace": "coreos", "usergroup": "team-a", "users": ["alice"]},
)
```

### Publishing Events (Producer -- Redis Streams)

Use the factory function -- never import concrete implementations directly:

```python
from qontract_utils.events.factory import create_event_publisher
from qontract_utils.events.models import Event

publisher = create_event_publisher("redis", client=redis_client, stream_key="qontract:events")
publisher.publish(Event(
    event_type="slack-usergroups.update_users",
    source="qontract-api",
    payload=action.model_dump(),
))
```

### Consuming Events (Consumer -- Redis Streams)

```python
from qontract_utils.events.factory import create_event_consumer

consumer = create_event_consumer(
    "redis", client=redis_client, stream_key="qontract:events",
    consumer_group="my-group", consumer_name="worker-1",
)
for message_id, event in consumer.receive():
    process(event)
    consumer.acknowledge(message_id)
```

### Configuration (qontract-api)

```yaml
events:
  enabled: true
  stream_key: "qontract:events"
```

The Redis connection is reused from the existing cache backend (`cache.client`).

### Checklist

- [ ] Event publishing is behind a feature flag (`events.enabled`)
- [ ] Publishing failures do not break the producer
- [ ] Use factory functions, not concrete implementations
- [ ] Consumers acknowledge messages only after successful processing
- [ ] Event types use dot-separated naming (`integration.action`)

## References

- Related ADRs: ADR-011 (Dependency Injection), ADR-012 (Typed Models), ADR-014 (Three-Layer Architecture), ADR-017 (Factory Pattern)
- Event API: `qontract_utils/qontract_utils/events/`
- Factory: `qontract_utils/qontract_utils/events/factory.py`
- Protocols: `qontract_utils/qontract_utils/events/protocols.py`
- Redis Streams: `qontract_utils/qontract_utils/events/redis_streams.py`
- SNS/SQS (alternative): `qontract_utils/qontract_utils/events/sns_sqs.py`
- Event log sink integration: `reconcile/event_log_sink/integration.py`
