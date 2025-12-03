# ADR-007: No Changes to reconcile/ - Migrate Utilities to qontract_utils

**Status:** Accepted
**Date:** 2025-11-14
**Authors:** cassing
**Supersedes:** N/A
**Superseded by:** N/A

## Context

The qontract-api is being developed as a new service alongside the existing qontract-reconcile codebase. This raises questions about:

- **Code sharing**: Can qontract-api import from `reconcile/`?
- **Dependencies**: Should qontract-api depend on reconcile code?
- **Modifications**: Can we modify `reconcile/` code to support qontract-api?
- **Utilities**: What about shared utilities in `reconcile/utils/`?

### Current Situation

**qontract-reconcile structure:**

```
qontract-reconcile/
├── reconcile/              # 158 integration modules
│   ├── utils/              # Shared utilities (25+ modules)
│   ├── aws_*/              # AWS integrations
│   ├── slack_*/            # Slack integrations
│   └── ...
├── reconcile/gql_definitions/  # Auto-generated GraphQL classes
└── qontract_utils/        # Shared utilities library
```

**Problems:**

1. **`reconcile/` is not a library** - It's a runnable integration collection, not designed for import
2. **Circular dependencies risk** - If qontract-api imports from `reconcile/`, we create coupling
3. **`reconcile/utils` is internal** - Not designed as public API for external consumers
4. **Stability concerns** - `reconcile/` changes frequently, qontract-api needs stable dependencies
5. **Testing complexity** - Importing reconcile code brings unnecessary test dependencies

### Real Example: slack_usergroups Integration

**What we need:**

- Business logic from `reconcile/slack_usergroups.py` (300+ lines)
- Utilities from `reconcile/utils/` (sharding, config, helpers)
- GraphQL queries and dataclasses

**Current approach (problematic):**

```python
# qontract-api trying to import from reconcile/
from reconcile.slack_usergroups import get_desired_state  # ❌ WRONG
from reconcile.utils.sharding import is_in_shard          # ❌ WRONG
```

## Decision

**qontract-api MUST NOT modify or directly import from `reconcile/`. Instead, shared code must be migrated to `qontract_utils` as reusable, stable utilities.**

### Key Principles

1. **Read-Only Consumer**
   - qontract-api treats `reconcile/` as **read-only reference implementation**
   - Can read reconcile code for understanding business logic
   - **CANNOT** import or depend on `reconcile/` modules

2. **No Modifications to reconcile/**
   - qontract-api development **CANNOT** modify any `reconcile/` code
   - No adding hooks, interfaces, or abstractions to `reconcile/` for qontract-api
   - Keeps reconcile codebase independent and stable

3. **Migrate to qontract_utils**
   - Shared utilities move from `reconcile/utils/` → `qontract_utils/`
   - Business logic is **refactored** (not copied) to `qontract_utils/`
   - Both reconcile and qontract-api depend on `qontract_utils`

4. **Independent Implementations**
   - qontract-api reimplements integration logic as needed
   - Uses reconcile code as **reference**, not dependency
   - Allows qontract-api to evolve independently

### Benefits of Migration to qontract_utils

Migrating utilities from `reconcile/utils/` to `qontract_utils/` provides multiple quality and maintenance benefits:

#### Code Quality Improvements

- **Type safety** - Full type hints required (ruff enforced), catch errors at development time
- **Comprehensive testing** - >80% coverage required vs optional in reconcile/utils
- **Stricter linting** - More ruff checks enabled than reconcile (e.g., type hints, docstrings)
- **Code review enforced** - Migration PRs get thorough review, catch bugs and anti-patterns
- **Better documentation** - Comprehensive docstrings with examples required

#### API Improvements

- **Consistent APIs** - Fix inconsistent patterns (bool vs None vs value returns)
- **Breaking changes allowed** - Can fix bad APIs without breaking reconcile
- **Modern standards** - Update to latest Python patterns (e.g., `StrEnum` vs `str, Enum`)
- **Deprecated APIs avoided** - Replace deprecated libraries (e.g., `aws_api` → `aws_api_typed`)
- **Clear error messages** - Descriptive exceptions help debugging

#### Maintenance Benefits

- **Independent evolution** - Both reconcile and qontract-api benefit from improvements
- **No reconcile pollution** - reconcile stays focused on CLI integrations
- **Reusable** - Single source of truth for both systems
- **Safe rollback** - Original reconcile code unchanged (see ADR-008 for rollback strategy)

#### Examples of Improvements

**Type Safety:**

- Before: `def validate_email(email)` - No type hints, runtime errors
- After: `def validate_email(email: str) -> str` - Type-safe, IDE support

**Deprecated APIs:**

- Before: `reconcile/utils/aws_api.py` - Uses deprecated boto patterns
- After: `qontract_utils/aws_api_typed.py` - Modern boto3 with type stubs

**Consistent APIs:**

- Before: Some functions return `None` on error, some `False`, some raise
- After: All functions raise `ValueError` with descriptive messages

**Testing:**

- Before: `reconcile/utils/` - 0% test coverage, bugs in production
- After: `qontract_utils/` - >80% coverage, bugs caught in CI

**Documentation:**

- Before: No docstrings, unclear what's valid input
- After: Comprehensive docstrings with examples, Args, Returns, Raises

### What Gets Migrated to qontract_utils

**High Priority (needed for POC):**

- **Sharding logic** - Used by many integrations for horizontal scaling
- **Common data structures** - Shared models, dataclasses
- **Validation utilities** - Input validation, schema checking
- **API clients** - SlackApi (already done), GitHubApi, GitLabApi (future)

**Medium Priority (post-POC):**

- **Configuration helpers** - Settings parsing, validation
- **Cache abstractions** - Already done (Redis cache backend)
- **Metrics helpers** - Prometheus metrics utilities

**NOT Migrated:**

- **Integration-specific logic** - Stays in `reconcile/` or `qontract_api/integrations/`
- **GraphQL queries** - Stay in integration modules
- **CLI tools** - Stay in `reconcile/` or `tools/`

### Example: slack_usergroups Migration

**reconcile/slack_usergroups.py (reference implementation):**

```python
# Read-only reference - DO NOT IMPORT
def run(dry_run: bool) -> None:
    """Reconcile Slack usergroups (CLI integration)."""
    # 1. Fetch desired state from GraphQL
    # 2. Fetch current state from Slack API
    # 3. Calculate diff
    # 4. Apply changes (unless dry_run)
```

**qontract_api/integrations/slack_usergroups/service.py (new implementation):**

```python
# New implementation for API context - DOES NOT IMPORT reconcile/
from qontract_utils.slack_api import SlackApi  # ✓ Shared utility

class SlackUsergroupsService:
    """Slack usergroups reconciliation service.

    Refactored from reconcile/slack_usergroups.py for API context.
    Adds caching, async support, and webhook capabilities.
    """

    def reconcile(self, dry_run: bool) -> ReconcileResult:
        """Reconcile Slack usergroups (API integration)."""
        # Similar logic to reconcile/slack_usergroups.py
        # But adapted for API context with caching, etc.
```

## Alternatives Considered

### Alternative 1: Import from reconcile/ (Rejected)

qontract-api directly imports from `reconcile/` modules.

**Pros:**

- No code duplication
- Reuse existing logic
- Quick to implement

**Cons:**

- **Tight coupling** - Changes in reconcile break qontract-api
- **Circular dependency risk** - reconcile might want to use qontract-api
- **Import hell** - reconcile/ not designed as importable library
- **Testing complexity** - Brings all reconcile test dependencies
- **Unstable API** - reconcile/ changes frequently without semantic versioning

### Alternative 2: Modify reconcile/ for qontract-api (Rejected)

Add abstractions/hooks to `reconcile/` modules to support qontract-api.

**Pros:**

- Shared codebase
- Single source of truth

**Cons:**

- **Pollutes reconcile codebase** - Adds complexity for qontract-api needs
- **Breaks separation of concerns** - reconcile becomes library + CLI
- **Harder to maintain** - Changes affect both systems
- **Deployment coupling** - Must deploy both together
- **Risky** - Breaking changes affect production reconcile

### Alternative 3: Shared qontract_utils Library (Selected)

Migrate reusable code to `qontract_utils`, both systems depend on it.

**Pros:**

- **Clean separation** - reconcile and qontract-api are independent
- **Stable API** - qontract_utils has semantic versioning
- **Reusable** - Both systems benefit from shared utilities
- **Testable** - Utilities tested independently
- **No coupling** - Systems evolve independently
- **Clear ownership** - qontract_utils is library, reconcile is CLI, qontract-api is service

**Cons:**

- **Migration effort** - Must refactor code to qontract_utils
  - **Mitigation:** Incremental migration, start with high-value utilities
- **Initial duplication** - Some logic temporarily duplicated during migration
  - **Mitigation:** Prioritize migration of shared utilities first

## Consequences

### Positive

1. **Clean architecture** - Clear boundaries between reconcile CLI and qontract-api service
2. **Independent evolution** - Both systems evolve without breaking each other
3. **Stable dependencies** - qontract-api depends on stable `qontract_utils`, not volatile `reconcile/`
4. **Better testing** - No need to import entire reconcile codebase for tests
5. **Shared utilities** - Both systems benefit from improved utilities in qontract_utils
6. **No pollution** - reconcile codebase stays focused on CLI integrations
7. **Semantic versioning** - qontract_utils can use proper versioning for breaking changes
8. **Code quality improvement** - Migration enforces code review, stricter linting, better docs
9. **Modernization opportunity** - Update to latest Python standards, type hints, best practices
10. **Breaking changes allowed** - Can fix bad APIs in qontract_utils without breaking reconcile
11. **Consistent standards** - qontract_utils enforces higher code quality bar than reconcile
12. **Deprecated APIs avoided** - Replace deprecated libraries (e.g., `aws_api` → `aws_api_typed` with modern boto3)

### Negative

1. **Migration effort** - Requires refactoring utilities from reconcile/utils to qontract_utils
   - **Mitigation:** Incremental migration during POC development
   - **Mitigation:** Prioritize high-value utilities (sharding, SlackApi, etc.)

2. **Temporary duplication** - Some logic duplicated during migration period
   - **Mitigation:** Migrate shared utilities first to minimize duplication
   - **Mitigation:** Document which utilities are migrated vs pending

3. **Learning curve** - Developers must understand three codebases (reconcile, qontract-api, qontract_utils)
   - **Mitigation:** Clear documentation in each codebase README
   - **Mitigation:** AGENTS.md provides guidance on when to use each

## Implementation Guidelines

### For qontract-api Developers

**DO:**

- ✓ Import from `qontract_utils/`
- ✓ Read `reconcile/` code for reference/understanding
- ✓ Reimplement business logic in `qontract_api/integrations/`
- ✓ Migrate shared utilities to `qontract_utils/` (with tests!)

**DON'T:**

- ✗ Import from `reconcile/` modules
- ✗ Modify any `reconcile/` code for qontract-api needs
- ✗ Copy-paste from reconcile without refactoring
- ✗ Add qontract-api dependencies to reconcile

### Checklist for Migrating Utilities

When migrating a utility from `reconcile/utils/` to `qontract_utils/`:

- [ ] **Extract** - Copy utility to `qontract_utils/` with new module structure
- [ ] **Refactor** - Improve API, add type hints, simplify dependencies
- [ ] **Document** - Add comprehensive docstrings with examples
- [ ] **Test** - Write unit tests (>80% coverage)
- [ ] **Migrate reconcile** - Update reconcile (**qontract-api enabled integrations only**) to import from qontract_utils (separate PR)
- [ ] **Verify** - Ensure both reconcile and qontract-api work with new utility

### Example Migration Workflow

1. **Identify** utility needed by qontract-api (e.g., `reconcile/utils/sharding.py`)
2. **Refactor** to `qontract_utils/sharding.py` with improved API
3. **Test** with comprehensive unit tests
4. **Use in qontract-api** - Import from `qontract_utils.sharding`
5. **Update reconcile** (future) - Migrate reconcile to use `qontract_utils.sharding`

## References

- Related: [ADR-001](ADR-001-use-adrs-for-architecture-decisions.md) - ADR process
- Related: [ADR-002](ADR-002-client-side-graphql-fetching.md) - Client-side GraphQL (reconcile owns queries)
- Codebase: `reconcile/` - Read-only reference implementation
- Codebase: `qontract_utils/` - Shared utilities library
- Codebase: `qontract_api/` - API service implementation

## Notes

This ADR establishes a fundamental architectural principle: **qontract-api and qontract-reconcile are independent systems that share utilities via qontract_utils, but do not depend on each other's implementation code.**

During the POC phase, we will incrementally migrate utilities as needed. The goal is NOT to migrate everything from `reconcile/utils/` upfront, but rather to migrate utilities **as they are needed** by qontract-api, ensuring each migration improves the utility's API and test coverage.

### Quality Benefits of Migration

Each migration to qontract_utils is an opportunity to improve code quality:

- **Code review** - Migration PRs require review, catching bugs and anti-patterns
- **Stricter linting** - qontract_utils enables more ruff checks than reconcile (e.g., type hints required)
- **Breaking changes** - Can fix bad APIs without breaking existing reconcile code
- **Modernization** - Update to latest Python standards (e.g., `StrEnum` instead of `str, Enum`)
- **Deprecated APIs** - Replace deprecated libraries (e.g., `aws_api` → `aws_api_typed` with modern boto3)
- **Documentation** - Migration requires comprehensive docstrings with examples
- **Testing** - Migration requires >80% test coverage, unlike reconcile/utils

Examples: Fix inconsistent return types (bool vs None vs value), add full type hints, replace deprecated AWS SDK, comprehensive docstrings, >80% test coverage - improvements that would break 50+ reconcile integrations if done directly.

### Future Considerations

After the POC, we may:

1. **Migrate more utilities** - Incrementally move more `reconcile/utils/` to `qontract_utils/`
2. **Shared models** - Extract common data models to `qontract_utils/`
3. **Update reconcile** - Migrate reconcile to depend on `qontract_utils/` (low priority)
4. **Deprecate reconcile/utils** - Eventually deprecate `reconcile/utils/` in favor of `qontract_utils/`

But these are future considerations - for the POC, the principle is clear: **no imports from reconcile/, migrate to qontract_utils as needed**.
