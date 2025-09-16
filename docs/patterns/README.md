# `qontract-reconcile` Design Patterns

This documentation provides an overview of the key architectural and implementation patterns used throughout the `qontract-reconcile` project. Understanding these patterns is essential for developing new integrations and maintaining existing ones.

## Architectural Patterns

These patterns describe the high-level structure and core concepts of the project.

*   **[The Core Reconciliation Loop](./reconciliation-loop.md)**
    The fundamental `desired vs. current` state logic that forms the basis of every integration.

*   **[The Integration Deployment Model](./integration-deployment-model.md)**
    How integrations are defined in `app-interface` and deployed as runnable Kubernetes resources.

*   **[Sharding](./sharding.md)**
    The horizontal scaling strategy used to divide an integration's workload into parallel jobs.

*   **[GraphQL Data Binding with `qenerate`](./gql-data-binding.md)**
    The standard, type-safe workflow for fetching data from `app-interface` using GraphQL and Pydantic.

## Implementation Patterns

These patterns cover the common, hands-on techniques used to build robust and maintainable integrations.

*   **[OpenShift Resource Management](./openshift-resource-management.md)**
    The standardized, declarative pattern for managing OpenShift resources using a `ResourceInventory`.

*   **[Declarative "Plan and Apply" Logic](./plan-and-apply-logic.md)**
    The practice of separating the calculation of changes from their execution to ensure safe and auditable `dry-run` behavior.

*   **[Client Factories and Managers](./client-factories.md)**
    The use of centralized factories to provide consistent, pre-configured API clients for services like OpenShift and AWS.

*   **[Secret Management with Vault](./secret-management.md)**
    The secure and standardized workflow for accessing secrets from HashiCorp Vault.

*   **[Caching and Early Exit](./caching-and-early-exit.md)**
    Performance optimization techniques (`early_exit` and `extended_early_exit`) that prevent redundant integration runs.

*   **[State Management](./state-management.md)**
    The pattern for persisting data and state between integration runs using an S3-backed utility.

*   **[Concurrency with Thread Pools](./concurrency-with-thread-pools.md)**
    The standard approach to using thread pools for performing I/O-bound operations in parallel.

*   **[Testing Strategies](./testing-strategies.md)**
    Common techniques for writing effective and isolated unit tests using `pytest` and mocking.

*   **[Observability: Logging and Metrics](./observability.md)**
    Best practices for structured logging and exposing Prometheus metrics for monitoring.
