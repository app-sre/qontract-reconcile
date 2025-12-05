# ADR-001: Use Architecture Decision Records for Architecture Decisions

**Status:** Accepted
**Date:** 2025-11-14
**Authors:** cassing

## Context

The qontract-api POC involves many important architecture decisions that will impact:

- System boundaries and responsibilities
- Integration patterns and conventions
- Execution models and workflows
- Code organization and reusability

Without proper documentation, these decisions:

- Are lost in code reviews or chat discussions
- Lack context for why they were made
- Are hard to revisit or challenge
- Make onboarding difficult for new developers
- Lead to inconsistent implementations

## Decision

**We will use Architecture Decision Records (ADRs) to document all significant architecture decisions in the qontract-reconcile.**

### Difference Between ADRs and Design Documents

**ADRs** document a single, specific architectural decision with its context, alternatives, and rationale. The scope is narrow - one decision at a time (e.g., "Should we use REST or GraphQL?", "Redis vs DynamoDB for caching?"). The audience is primarily developers and architects.

**Design documents** are broader, and describe the overall solution to a problem, including architecture, implementation plan, and trade-offs. The scope is wide and covers entire features or systems (e.g. the qontract-api concept). The audience includes stakeholders, PMs, and developers.

### What Qualifies as "Significant"

An architecture decision should be documented as an ADR if it:

1. **Defines system boundaries**
   - Example: Client-side vs API-side GraphQL fetching
   - Example: What responsibilities belong to the API vs the client

1. **Establishes cross-cutting patterns**
   - Example: Generic hook system for API wrappers
   - Example: Centralized rate limiting approach

1. **Affects multiple components**
   - Example: Sync-first development with async when needed
   - Example: Direct vs queued execution modes

1. **Has non-obvious tradeoffs**
   - Example: Custom Redis locks vs external libraries
   - Example: Where to implement rate limiting

1. **Sets naming conventions or coding standards**
   - Example: `method()` for sync, `async_method()` for async
   - Example: Hook naming and signature patterns

### What Does NOT Need an ADR

The following are implementation details or standard choices that should be documented elsewhere (README, technical docs):

- **Technology choices**: Redis, FastAPI, Celery, PostgreSQL
  - Document in: `README.md`, architecture diagrams

- **Standard patterns**: JWT authentication, cache abstraction
  - Document in: Technical documentation, code comments

- **Project structure**: Monorepo setup, workspace configuration
  - Document in: `README.md`, `CONTRIBUTING.md`

- **Implementation details**: Specific algorithms, data structures
  - Document in: Code comments, docstrings

### ADR Process

1. **Format**: Use [ADR-000 template](ADR-000-template.md)
1. **Numbering**: Sequentially number ADRs (ADR-001, ADR-002, etc.) and maintain an index in `docs/adr/README.md`
1. **Living Documents**: ADRs can be updated over time (add learnings, update examples, ...) or superseded by new ADRs.
1. **Review**: All ADRs must be reviewed and must reach consensus before being accepted/merged.
1. **Maintenance**: Periodically review ADRs to ensure they remain relevant

## Alternatives Considered

### Alternative 1: No Formal Documentation

Document decisions in README or wiki.

**Pros:**

- Less overhead
- More flexible

**Cons:**

- Decisions get lost in large documents
- No structure for rationale
- Hard to find specific decisions
- No alternatives/tradeoffs documented

### Alternative 2: Detailed Design Documents

Write comprehensive design docs for every feature.

**Pros:**

- Very thorough
- Includes implementation details

**Cons:**

- Too heavy for POC
- Hard to maintain
- Developers don't read long docs
- Becomes outdated quickly

### Alternative 3: ADRs (Selected)

Lightweight, focused records for architecture decisions.

**Pros:**

- Focused on WHY, not HOW
- Easy to write and read
- Searchable and indexable
- Industry-standard format
- Living documents that evolve

**Cons:**

- Requires discipline to write
  - **Mitigation:** Template makes it easy

## Consequences

### Positive

1. **Better decision-making**: Forces us to consider alternatives
2. **Clearer communication**: Team understands WHY decisions were made
3. **Easier onboarding**: New developers can read ADR history
4. **Reviewable decisions**: Can revisit and challenge decisions with context
5. **Knowledge retention**: Decisions don't live only in people's heads
6. **Consistency**: Establishes patterns that apply across the codebase

### Negative

1. **Extra work**: Writing ADRs takes time
   - **Mitigation:** Template makes it quick (~15-30 minutes per ADR)
   - **Mitigation:** Only for significant decisions, not everything

2. **Can become stale**: ADRs might not reflect current implementation
   - **Mitigation:** POC ADRs are living documents, update as we learn
   - **Mitigation:** Keep ADRs focused on decision, not implementation

## Implementation Guidelines

### When to Write an ADR

**DO write an ADR when:**

- Designing a new integration pattern
- Making a choice between multiple approaches
- Establishing a naming convention
- Defining system boundaries
- Making decisions that affect multiple components

**DON'T write an ADR for:**

- Choosing a library for a specific task
- Implementation details of a single feature
- Bug fixes or refactoring
- Standard patterns (caching, etc.)

### How to Write an ADR

1. **Start with template**: Copy [ADR-000-template.md](ADR-000-template.md)
1. **Number sequentially**: Next available ADR number
1. **Clear title**: Describe the decision, not the problem
1. **Status**: "Accepted" for all new ADRs
1. **Context first**: Explain the problem/situation
1. **Decision**: State clearly what we decided
1. **Alternatives**: Show what else we considered and why we didn't choose it
1. **Consequences**: Honest assessment of tradeoffs
1. **Keep it short**: Aim for 100-200 lines, not 500+
1. **Use AI tools**: Leverage AI to draft ADRs quickly, then refine (e.g. use `/adr` Claude command)

### ADR Lifecycle

```
Accepted ──> Update as needed ──> Still Accepted
          │
          └──> Superseded or Deprecated
```

## References

- ADR template: [ADR-000-template.md](ADR-000-template.md)
- ADR index: [README.md](README.md)
- External: [Michael Nygard's ADR article](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions)
- External: [adr.github.io](https://adr.github.io/)

## Notes

This is the first ADR for qontract-reconcile. It establishes the framework for all future architecture decisions. As the project evolves, we may refine this process, but the core principle remains: **document significant architecture decisions with clear rationale**.
