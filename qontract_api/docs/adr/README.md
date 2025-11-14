# Architecture Decision Records (ADRs)

This directory contains Architecture Decision Records (ADRs) for the qontract-api POC.

## What is an ADR?

An Architecture Decision Record (ADR) documents an important architecture decision made along with its context and consequences. See [ADR-001](ADR-001-use-adrs-for-architecture-decisions.md) for our ADR process.

## Index

| ADR                                                                         | Title                                              | Status         | Date       |
| --------------------------------------------------------------------------- | -------------------------------------------------- | -------------- | ---------- |
| [ADR-000](ADR-000-template.md)                                              | Template for ADRs                                  | Template       | -          |
| [ADR-001](ADR-001-use-adrs-for-architecture-decisions.md)                   | Use ADRs for Architecture Decisions                | Proposed (POC) | 2025-11-14 |
| [ADR-002](ADR-002-client-side-graphql-fetching.md)                          | Client-Side GraphQL Fetching Only                  | Proposed (POC) | 2025-11-14 |
| [ADR-003](ADR-003-direct-vs-queued-execution-modes.md)                      | Direct vs Queued Execution Modes                   | Proposed (POC) | 2025-11-14 |
| [ADR-004](ADR-004-centralized-rate-limiting-via-hooks.md)                   | Centralized Rate Limiting via Hooks                | Proposed (POC) | 2025-11-14 |
| [ADR-005](ADR-005-sync-only-no-async.md)                                    | Async/Sync Method Guidelines                       | Proposed       | 2025-11-19 |
| [ADR-006](ADR-006-generic-hook-system-slack-api.md)                         | Generic Hook System for API Wrappers               | Proposed (POC) | 2025-11-14 |
| [ADR-007](ADR-007-no-reconcile-changes-migrate-utils.md)                    | No Changes to reconcile/ - Migrate Utils           | Proposed (POC) | 2025-11-14 |
| [ADR-008](ADR-008-client-integration-pattern.md)                            | Client Integration Pattern for qontract-api        | Proposed (POC) | 2025-11-14 |
| [ADR-009](ADR-009-structured-json-logging.md)                               | Structured JSON Logging for Production Systems     | Proposed       | 2025-11-18 |
| [ADR-011](ADR-011-dependency-injection-pattern.md)                          | Dependency Injection for External Resources        | Proposed       | 2025-11-18 |
| [ADR-012](ADR-012-typed-models-over-dicts.md)                               | Fully Typed Pydantic Models Over Nested Dicts      | Proposed       | 2025-11-19 |
| [ADR-013](ADR-013-centralize-external-api-calls.md)                         | Centralize External API Calls in API Gateway       | Proposed       | 2025-11-18 |
| [ADR-014](ADR-014-three-layer-architecture-for-external-apis.md)            | Three-Layer Architecture for External API Integrations | Accepted   | 2025-11-18 |
| [ADR-015](ADR-015-cache-update-strategy.md)                                 | Cache Update Instead of Invalidation               | Proposed       | 2025-11-18 |
| [ADR-016](ADR-016-two-tier-cache.md)                                        | Two-Tier Cache Architecture (Memory + Redis)       | Proposed       | 2025-11-20 |

## ADR Categories

### System Boundaries

- [ADR-002](ADR-002-client-side-graphql-fetching.md) - Client-side GraphQL fetching
- [ADR-007](ADR-007-no-reconcile-changes-migrate-utils.md) - No reconcile/ imports, migrate to qontract_utils
- [ADR-008](ADR-008-client-integration-pattern.md) - Client integration pattern (`_api` suffix)
- [ADR-013](ADR-013-centralize-external-api-calls.md) - Centralize external API calls in qontract-api

### Execution Patterns

- [ADR-003](ADR-003-direct-vs-queued-execution-modes.md) - Direct vs queued modes

### Cross-Cutting Concerns

- [ADR-004](ADR-004-centralized-rate-limiting-via-hooks.md) - Rate limiting approach
- [ADR-006](ADR-006-generic-hook-system-slack-api.md) - Generic hook system
- [ADR-009](ADR-009-structured-json-logging.md) - Structured JSON logging (production vs development)

### Architecture Patterns

- [ADR-011](ADR-011-dependency-injection-pattern.md) - Dependency injection for external resources
- [ADR-014](ADR-014-three-layer-architecture-for-external-apis.md) - Three-layer architecture for external APIs
- [ADR-015](ADR-015-cache-update-strategy.md) - Cache update strategy (update vs invalidation)
- [ADR-016](ADR-016-two-tier-cache.md) - Two-tier cache (memory + Redis) for performance

### Code Conventions

- [ADR-005](ADR-005-sync-only-no-async.md) - Async/Sync method guidelines (default sync, async for FastAPI-only)
- [ADR-012](ADR-012-typed-models-over-dicts.md) - Fully typed immutable Pydantic models (frozen=True)

### Process

- [ADR-001](ADR-001-use-adrs-for-architecture-decisions.md) - ADR process itself

## Status Definitions

- **Proposed (POC)**: Decision made for POC, open to refinement during development
- **Accepted**: Decision is final and should be followed
- **Superseded**: Decision has been replaced by a newer ADR
- **Deprecated**: Decision is no longer valid but kept for historical reference

## Creating a New ADR

1. Copy [ADR-000-template.md](ADR-000-template.md)
2. Use next available number: `ADR-XXX-short-title.md`
3. Fill in all sections
4. Add entry to this README index
5. Submit for review

See [ADR-001](ADR-001-use-adrs-for-architecture-decisions.md) for full guidelines on when and how to write ADRs.
