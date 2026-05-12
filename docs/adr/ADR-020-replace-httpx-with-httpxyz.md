# ADR-020: Replace httpx with httpxyz

**Status:** Accepted
**Date:** 2026-05-12
**Authors:** chassing
**Supersedes:** N/A
**Superseded by:** N/A

## Context

`httpx` is the HTTP client used throughout qontract-reconcile, qontract-utils, qontract-api, and qontract-api-client — both directly and as a transitive dependency of libraries like `pagerduty`, `openapi-python-client`, and the Anthropic SDK.

**httpx maintenance has effectively stopped:**

- No release after November 2024, despite several bugs affecting real-world usage remaining unresolved
- A critical zstandard content decoding fix was submitted but ignored — no patch release followed
- Repeated requests for releases — including personal emails to the author — went unanswered
- Issues and discussions were closed, removing visibility into bugs and contribution pathways
- Documentation and code links broke due to these closures
- A promised 1.0 rewrite has been discussed since 2020 without materializing
- A draft 0.28.2 patch remained open for over a year without release
- Breaking changes appeared in minor releases, contradicting semantic versioning expectations
- Major downstream packages (OpenAI, Anthropic SDKs) already pin `httpx < 1.0` as a guard

**httpxyz** is a community fork started by the original httpx contributor community after the maintainer became unresponsive. It prioritizes stability through bug fixes and API compatibility rather than ambitious rewrites. Two maintainers share the workload to prevent single-point-of-failure burnout. See [httpxyz.org/why-fork](https://httpxyz.org/why-fork/) for the full rationale.

**Transitive dependency challenge:** Libraries like `pagerduty` do `import httpx` internally. httpxyz handles this by registering itself as `sys.modules["httpx"]` via `setdefault` on import, so any subsequent `import httpx` resolves to httpxyz. This mechanism is import-order-dependent and requires httpxyz to be imported before any library that uses httpx.

## Decision

**Replace httpx with httpxyz project-wide and centralize the `sys.modules` registration in a compatibility module (`qontract_utils._httpxyz_compat`).**

### Key Points

- **Drop-in replacement:** httpxyz is fully API-compatible with httpx 0.28.x — all existing code works with a simple import rename
- **Centralized registration:** A `_httpxyz_compat` module in `qontract_utils` imports httpxyz early (from `__init__.py`) and asserts that `sys.modules["httpx"]` points to httpxyz. This eliminates fragile import-order tricks in individual modules
- **Runtime guard:** The compat module raises `RuntimeError` if real httpx was loaded before httpxyz, turning a silent runtime mystery into a clear failure
- **Transitive deps covered:** Because `qontract_utils` is imported early by all packages in the workspace, the registration happens before any transitive dependency can `import httpx`

### Re-evaluation Criteria

This decision should be revisited if any of the following occur:

1. **httpxyz goes dormant** — no releases for 6+ months, unresponsive maintainers (same problems as httpx)
2. **httpx resumes active maintenance** — new maintainer, regular releases, issues reopened
3. **A superior alternative emerges** — e.g., httpx 1.0 actually ships and is stable
4. **Supply-chain incident** — security vulnerability in httpxyz that isn't promptly addressed

## Alternatives Considered

### Alternative 1: Stay on httpx

Continue using the unmaintained httpx package.

**Pros:**

- No migration effort
- Massive ecosystem adoption (top-100 PyPI, 500k+ dependent repos)

**Cons:**

- No bug fixes or security patches
- Known bugs remain unresolved
- No avenue for reporting or tracking issues (issues/discussions closed)
- Risk of silent breakage in future Python versions

### Alternative 2: Vendor httpx

Fork httpx internally and maintain our own copy.

**Pros:**

- Full control over patches
- No external dependency risk

**Cons:**

- Significant maintenance burden — we'd become httpx maintainers
- Must track upstream changes and security advisories ourselves
- Doesn't solve transitive dependency problem (pagerduty et al. still `import httpx`)

### Alternative 3: Switch to aiohttp / urllib3

Replace httpx with a different HTTP client entirely.

**Pros:**

- Well-maintained alternatives with large communities

**Cons:**

- Different API — requires rewriting all HTTP client code, not a drop-in
- Doesn't solve transitive dependency problem
- `openapi-python-client` templates are built around httpx API

### Alternative 4: httpxyz (Selected)

Use the community fork that maintains API compatibility.

**Pros:**

- Drop-in replacement — minimal migration effort
- Active maintenance with bug fixes
- `sys.modules` registration handles transitive dependencies transparently
- Two maintainers to avoid single-point-of-failure
- Community-driven with clear governance

**Cons:**

- Young fork (2025) — less battle-tested than httpx
  - **Mitigation:** API-compatible with httpx 0.28.x, same codebase, same test suite
- Smaller community than httpx
  - **Mitigation:** Growing adoption (NiceGUI, others migrating). Re-evaluate per criteria above
- Supply-chain risk of depending on a new package
  - **Mitigation:** Centralized compat module makes switching back trivial if needed

## Consequences

### Positive

- Active maintenance — bug fixes and security patches available
- Transparent handling of transitive dependencies via `sys.modules` registration
- Centralized compat module eliminates fragile import-order dependencies
- Runtime assertion catches misconfiguration immediately instead of silently breaking
- Trivial to switch back if httpx resumes maintenance (change one module)

### Negative

- Dependency on a younger, less established package
  - **Mitigation:** Re-evaluation criteria defined above; compat module makes reversal easy
- `sys.modules` mechanism is implicit — developers must understand why `import httpx` resolves to httpxyz
  - **Mitigation:** ADR documents the mechanism; compat module has clear docstring; runtime assertion catches violations

## Implementation Guidelines

### Compatibility Module

The `_httpxyz_compat` module in `qontract_utils` centralizes the httpxyz registration:

```python
"""httpxyz forward-compatibility module.

httpxyz registers itself as sys.modules["httpx"] on import, so any library
doing `import httpx` transparently gets httpxyz. This module ensures httpxyz
is loaded early and guards against real httpx sneaking in.

See ADR-020 for rationale.
"""

import sys

import httpxyz

_httpx = sys.modules.get("httpx")
if _httpx is not httpxyz:
    msg = (
        "httpxyz must be imported before any library that uses httpx. "
        f"sys.modules['httpx'] is {_httpx!r}, expected httpxyz. "
        "See ADR-020."
    )
    raise RuntimeError(msg)
```

Import from `qontract_utils/__init__.py`:

```python
from qontract_utils import _httpxyz_compat  # noqa: F401
```

### Checklist

- [x] Replace `httpx` with `httpxyz` in all direct imports
- [x] Update all `pyproject.toml` dependency declarations
- [x] Create `qontract_utils/_httpxyz_compat.py`
- [x] Import compat module from `qontract_utils/__init__.py`

## References

- httpxyz rationale: [httpxyz.org/why-fork](https://httpxyz.org/why-fork/)
- NiceGUI migration: [nicegui#6024](https://github.com/zauberzeug/nicegui/issues/6024), [nicegui PR #148](https://github.com/evnchn/nicegui/pull/148)
- Implementation PR: [qontract-reconcile#5534](https://github.com/app-sre/qontract-reconcile/pull/5534)
- Implementation: `qontract_utils/qontract_utils/_httpxyz_compat.py`
- Ticket: [APPSRE-14239](https://redhat.atlassian.net/browse/APPSRE-14239)
