# ADR-001: Use Architecture Decision Records for Architecture Decisions

**Status:** Proposed
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

**We will use Architecture Decision Records (ADRs) to document all significant architecture decisions in the qontract-api POC.**

### What Qualifies as "Significant"

An architecture decision should be documented as an ADR if it:

1. **Defines system boundaries**
   - Example: Client-side vs API-side GraphQL fetching
   - Example: What responsibilities belong to the API vs the client

2. **Establishes cross-cutting patterns**
   - Example: Generic hook system for API wrappers
   - Example: Centralized rate limiting approach

3. **Affects multiple components**
   - Example: Sync-first development with async when needed
   - Example: Direct vs queued execution modes

4. **Has non-obvious tradeoffs**
   - Example: Custom Redis locks vs external libraries
   - Example: Where to implement rate limiting

5. **Sets naming conventions or coding standards**
   - Example: `method()` for sync, `async_method()` for async
   - Example: Hook naming and signature patterns

### What Does NOT Need an ADR

The following are implementation details or standard choices that should be documented elsewhere (README, technical docs):

- **Technology choices**: Redis, FastAPI, Celery, PostgreSQL
  - Document in: `README.md`, architecture diagrams

- **Standard patterns**: Dependency injection, JWT authentication, cache abstraction
  - Document in: Technical documentation, code comments

- **Project structure**: Monorepo setup, workspace configuration
  - Document in: `README.md`, `CONTRIBUTING.md`

- **Implementation details**: Specific algorithms, data structures
  - Document in: Code comments, docstrings

### ADR Process for POC

Since this is a POC (Proof of Concept):

1. **Status**: All ADRs start as **"Proposed (POC)"**
   - No "Accepted" needed during POC phase
   - We can freely modify/update ADRs as we learn

2. **No Migration Sections**: POC code can change without migration path
   - ADRs focus on decision rationale, not migration

3. **Living Documents**: ADRs can be updated during POC development
   - Add learnings, update examples, refine decisions

4. **Format**: Use [ADR-000 template](ADR-000-template.md)

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
- Standard patterns (DI, caching, etc.)

### How to Write an ADR

1. **Start with template**: Copy [ADR-000-template.md](ADR-000-template.md)
2. **Number sequentially**: Next available ADR number
3. **Clear title**: Describe the decision, not the problem
4. **Status**: "Proposed (POC)" for all POC ADRs
5. **Context first**: Explain the problem/situation
6. **Decision**: State clearly what we decided
7. **Alternatives**: Show what else we considered and why we didn't choose it
8. **Consequences**: Honest assessment of tradeoffs
9. **Keep it short**: Aim for 100-200 lines, not 500+

### ADR Lifecycle During POC

```
Proposed (POC) ──> Update as needed ──> Still Proposed (POC)
                          │
                          └──> After POC: Accepted or Superseded
```

## References

- ADR template: [ADR-000-template.md](ADR-000-template.md)
- ADR index: [README.md](README.md)
- External: [Michael Nygard's ADR article](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions)
- External: [adr.github.io](https://adr.github.io/)

## Notes

This is the first ADR for qontract-api POC. It establishes the framework for all future architecture decisions. As the POC evolves, we may refine this process, but the core principle remains: **document significant architecture decisions with clear rationale**.
