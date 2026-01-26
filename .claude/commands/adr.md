---
description: Create a new Architecture Decision Record (ADR)
---

# Architecture Decision Record (ADR) Creation

You are helping create a new Architecture Decision Record (ADR) for the qontract-api project.

## ADR Guidelines

- You are a senior software architect familiar with architectural patterns and best practices.
- ADRs document significant architectural decisions and patterns for the project.
- ADRs are stored in `docs/adr/`
- Use the template from `docs/adr/ADR-000-template.md`
- Read `docs/adr/ADR-001-use-adrs-for-architecture-decisions.md` for the ADR process and what qualifies as an ADR.
- ADRs must be **general architectural patterns**, NOT implementation-specific
- ADRs should include examples to illustrate the pattern
- The README at `docs/adr/README.md` must list all ADRs

## Workflow

1. **Determine ADR Number:**
   - Check existing ADRs in `docs/adr/` to find the highest number
   - If user didn't provide a number, propose the next available number
   - Ask user to confirm the number before proceeding

2. **Gather Information:**
   - Title (short, kebab-case)
   - Status (default: "Accepted")
   - Context (what problem are we solving?)
   - Decision (what are we doing?)
   - Key Points (3-5 main aspects)
   - Alternatives Considered (at least 2-3 alternatives with Pros/Cons)
   - Consequences (Positive and Negative with Mitigations)
   - Implementation Guidelines (optional, with code examples)
   - References (related ADRs, code, docs)

3. **Author Information:**
   - Use current system user (run `whoami`) as author
   - Date: Use today's date (YYYY-MM-DD format)

4. **Template Structure:**
   Follow the exact structure from ADR-000-template.md:
   - Headers: Status, Date, Authors
   - Context section
   - Decision section with Key Points
   - Alternatives Considered (REQUIRED - with Pros/Cons for each)
   - Consequences (Positive/Negative with Mitigations)
   - Implementation Guidelines (optional)
   - References
   - Notes (optional)

5. **Update README:**
   - Add new ADR entry to the index table in `docs/adr/README.md`
   - Keep table sorted by ADR number
   - Update categories section if introducing a new category

## Important Reminders

- ADRs document **architectural patterns**, not specific implementations
- Always include "Alternatives Considered" section with Pros/Cons
- Negative consequences must have **Mitigation** strategies
- Use examples to illustrate (e.g., "Example: Slack API Integration")
- Default status is "Proposed" unless user specifies otherwise
- Author is the current system user (from `whoami`), not "App-SRE Team"

## Example Usage

User: `/adr`
Assistant: I'll help you create a new ADR. Let me check the next available number...

[Determines next number is 016]

I propose ADR-016. Is this correct?

User: yes, title is "use-pydantic-for-api-models"
Assistant: [Asks for context, decision, alternatives, etc. and creates the ADR]
