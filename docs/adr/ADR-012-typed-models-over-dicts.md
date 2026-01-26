# ADR-012: Fully Typed Pydantic Models Over Nested Dicts

**Status:** Accepted
**Date:** 2025-11-14
**Authors:** cassing
**Supersedes:** N/A
**Superseded by:** N/A

## Context

API request and response structures can be represented in multiple ways: plain dictionaries, typed dictionaries (TypedDict), or Pydantic models. The choice affects type safety, validation, developer experience, and maintainability.

**Current Situation:**

- APIs exchange structured data (requests, responses, configuration)
- Data often has nested hierarchies (workspace → usergroup → config)
- Need validation of structure and types
- Developers need IDE support (autocompletion, type hints)
- Type checking with mypy is required

**Problems with Nested Dicts:**

- **No IDE autocompletion:** Can't discover available keys
- **Runtime errors:** Typos and wrong types only caught at runtime
- **Unclear structure:** What keys exist? What are their types?
- **No automatic validation:** Must manually validate every field
- **Hard to refactor:** Changes don't propagate through type system
- **Poor documentation:** Structure only visible in code or docs
- **Type safety gaps:** `dict[str, Any]` loses all type information

**Requirements:**

- Type-safe data structures (mypy catches errors)
- Automatic validation of structure and types
- Clear, self-documenting API contracts
- IDE autocompletion and type hints
- Easy to test with well-defined object structures
- Refactoring safety (type system propagates changes)

**Constraints:**

- Must work with FastAPI (JSON serialization/deserialization)
- Must integrate with mypy for type checking
- Should minimize boilerplate code
- Compatible with Python 3.12+

## Decision

We adopt **fully typed Pydantic models** with nested `BaseModel` classes for all API request/response structures.

Every level of nesting is represented by a dedicated Pydantic model class. No `dict[str, dict[str, X]]` types - instead use explicit model hierarchies.

### Key Points

- **Nested BaseModel classes:** Each structural level is a Pydantic model
- **Immutable models:** Use `model_config = ConfigDict(frozen=True)` to prevent modifications
- **No dict types for structured data:** Use models, not dicts
- **Type safety:** Full mypy checking through entire hierarchy
- **Automatic validation:** Pydantic validates on instantiation
- **Self-documenting:** Model structure IS the documentation

## Alternatives Considered

### Alternative 1: Nested Dictionaries

Use plain dictionaries with type hints like `dict[str, dict[str, Config]]`.

```python
class ReconcileRequest(BaseModel):
    workspaces: dict[str, dict[str, UsergroupConfig]]
    dry_run: bool = True

# Usage - no type safety inside dicts!
request = ReconcileRequest(
    workspaces={
        "app-sre": {
            "on-call": UsergroupConfig(...),
            "team": UsergroupConfig(...),
        }
    }
)

# No IDE help, runtime errors only
workspace_name = list(request.workspaces.keys())[0]
usergroup_data = request.workspaces[workspace_name]["on-call"]
# What fields does usergroup_data have? Unknown to IDE!
```

**Pros:**

- Minimal boilerplate (no extra model classes)
- Flexible structure (can add arbitrary keys)
- Familiar pattern (common in Python)

**Cons:**

- No IDE autocompletion inside dict structures
- Type information lost after first level (`dict[str, Any]`)
- Typos in keys only caught at runtime
- No validation of dict structure
- Hard to refactor (changes don't propagate)
- Unclear what structure looks like
- mypy can't help with nested access

### Alternative 2: TypedDict

Use `TypedDict` for structured dictionaries.

```python
from typing import TypedDict

class UsergroupDict(TypedDict):
    handle: str
    users: list[str]
    channels: list[str]

class WorkspaceDict(TypedDict):
    name: str
    usergroups: list[UsergroupDict]

class ReconcileRequest(BaseModel):
    workspaces: list[WorkspaceDict]
```

**Pros:**

- Type hints for dict keys
- mypy can check field access
- Less boilerplate than Pydantic models
- Works with standard library

**Cons:**

- No runtime validation (types are just hints)
- Can't use Pydantic features (validators, computed fields)
- Inconsistent (mixing TypedDict and BaseModel)
- No automatic JSON serialization
- Limited IDE support compared to classes
- Can't inherit from BaseModel

### Alternative 3: Fully Typed Pydantic Models (Selected)

Use nested Pydantic `BaseModel` classes for every structural level.

```python
class UsergroupConfig(BaseModel):
    users: list[str]
    channels: list[str]
    description: str = ""

class Usergroup(BaseModel):
    handle: str
    config: UsergroupConfig

class Workspace(BaseModel):
    name: str
    vault_token_path: str
    usergroups: list[Usergroup]

class ReconcileRequest(BaseModel):
    workspaces: list[Workspace]
    dry_run: bool = True

# Usage - full type safety and IDE support!
request = ReconcileRequest(
    workspaces=[
        Workspace(
            name="app-sre",
            vault_token_path="slack/app-sre/token",
            usergroups=[
                Usergroup(
                    handle="on-call",
                    config=UsergroupConfig(
                        users=["user1", "user2"],
                        channels=["#alerts"],
                    )
                )
            ]
        )
    ]
)

# IDE knows exact structure!
workspace = request.workspaces[0]
workspace.name  # ← IDE autocomplete works!
workspace.usergroups[0].config.users  # ← Fully typed!
```

**Pros:**

- **Full type safety:** mypy validates entire hierarchy
- **Automatic validation:** Pydantic checks types and structure
- **IDE autocompletion:** Works at every level
- **Self-documenting:** Model hierarchy shows structure
- **Easy testing:** Create test objects with known structure
- **Refactoring safety:** Type changes propagate
- **Validation features:** Can add validators, computed fields
- **JSON serialization:** `.model_dump()` and `.model_validate()` built-in

**Cons:**

- More boilerplate (extra model classes)
  - **Mitigation:** Boilerplate is documentation and type safety
  - **Mitigation:** Models are reusable across codebase

## Consequences

### Positive

- **Type safety:** mypy catches errors at development time, not runtime
- **Automatic validation:** Pydantic validates structure and types on instantiation
- **Immutability:** `frozen=True` prevents accidental modifications
- **Thread-safe:** Frozen models are inherently thread-safe
- **Self-documenting:** Model hierarchy is the documentation
- **IDE support:** Full autocompletion and type hints at every level
- **Easier testing:** Clear, testable object structure
- **Refactoring safety:** Changes propagate through type system
- **Runtime guarantees:** If object exists, structure is valid and unchanged
- **Better error messages:** Pydantic shows exactly what's wrong
- **Prevents unintended mutations:** No hidden state changes in deep call stacks

### Negative

- **More boilerplate:** Need to define model classes for each level
  - **Mitigation:** Models serve as documentation
  - **Mitigation:** Type safety worth the extra code
  - **Mitigation:** Models are reusable

- **Learning curve:** Developers must understand Pydantic
  - **Mitigation:** Pydantic is standard in FastAPI ecosystem
  - **Mitigation:** Document common patterns with examples

- **Verbose for simple structures:** Overkill for very simple data
  - **Mitigation:** Use TypedDict for truly simple cases (internal only)
  - **Mitigation:** API contracts benefit from formality

## Implementation Guidelines

### Pattern 1: Immutable Nested Model Hierarchy

Build models from bottom-up (leaf to root) with `frozen=True` for immutability:

```python
from pydantic import BaseModel, ConfigDict, Field

# Leaf level - configuration
class SlackUsergroupConfig(BaseModel):
    """Configuration for a Slack usergroup."""
    model_config = ConfigDict(frozen=True)  # ← Immutable

    users: list[str] = Field(default_factory=list)
    channels: list[str] = Field(default_factory=list)
    description: str = ""

# Mid level - usergroup
class SlackUsergroup(BaseModel):
    """A Slack usergroup with its configuration."""
    model_config = ConfigDict(frozen=True)  # ← Immutable

    handle: str
    config: SlackUsergroupConfig  # ← Nested model

# Mid level - workspace
class SlackWorkspace(BaseModel):
    """A Slack workspace with usergroups."""
    model_config = ConfigDict(frozen=True)  # ← Immutable

    name: str
    vault_token_path: str
    usergroups: list[SlackUsergroup]  # ← List of nested models

# Root level - request
class SlackUsergroupsReconcileRequest(BaseModel):
    """Request to reconcile Slack usergroups."""
    model_config = ConfigDict(frozen=True)  # ← Immutable

    workspaces: list[SlackWorkspace]  # ← Fully typed hierarchy
    dry_run: bool = True
```

**Why `frozen=True`?**

- **Prevents accidental mutations:** Cannot modify fields after creation
- **Thread-safe:** Immutable objects are inherently thread-safe
- **Hashable:** Can be used in sets/dicts (if all fields are hashable)
- **Clear intent:** Data is meant to be read, not modified
- **Prevents unintended mutations:** No hidden state changes deep in call stack

### Pattern 2: Modifying Immutable Models

Use `.model_copy()` to create modified copies:

```python
from pydantic import BaseModel, ConfigDict

class UserConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    age: int

# Create original
config = UserConfig(name="Alice", age=25)

# ❌ FAILS: Cannot modify frozen model
try:
    config.age = 26
except ValidationError:
    print("Cannot modify frozen model!")

# ✅ CORRECT: Create modified copy
updated = config.model_copy(update={"age": 26})
assert config.age == 25  # Original unchanged
assert updated.age == 26  # New copy with changes

# ✅ CORRECT: Create with dict merge
data = config.model_dump()
data["age"] = 26
updated = UserConfig.model_validate(data)
```

**When to use mutable vs immutable:**

- **Request/Response models:** Always immutable (`frozen=True`)
- **Configuration models:** Always immutable (`frozen=True`)
- **Internal state models:** May be mutable if needed (no `frozen=True`)

### Pattern 3: Avoid Redundancy

Don't duplicate data across model levels:

```python
# ❌ AVOID: Redundant data
class UsergroupConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    handle: str  # ← Redundant!
    users: list[str]

class Usergroup(BaseModel):
    model_config = ConfigDict(frozen=True)
    handle: str  # ← Already here
    config: UsergroupConfig  # ← Contains handle again!

# ✅ PREFER: Single source of truth
class UsergroupConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    users: list[str]
    # No handle - it's in parent Usergroup

class Usergroup(BaseModel):
    model_config = ConfigDict(frozen=True)
    handle: str  # ← Only here
    config: UsergroupConfig
```

### Pattern 4: Use Field Defaults

Provide sensible defaults with `Field`:

```python
from pydantic import BaseModel, ConfigDict, Field

class MyConfig(BaseModel):
    """Configuration with defaults."""
    model_config = ConfigDict(frozen=True)

    # Required field
    name: str

    # Optional with None
    description: str | None = None

    # Optional with default value
    timeout: int = 30

    # List with empty default
    tags: list[str] = Field(default_factory=list)

    # Dict with empty default
    metadata: dict[str, str] = Field(default_factory=dict)
```

### Pattern 5: Type Validation

Pydantic validates types automatically:

```python
class UserConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    username: str
    age: int
    active: bool

# Pydantic validates and coerces types
config = UserConfig(
    username="alice",
    age="25",  # ← String coerced to int
    active=1,   # ← Int coerced to bool
)

assert config.age == 25
assert config.active is True

# Validation errors
try:
    UserConfig(username="bob", age="invalid", active=True)
except ValidationError as e:
    print(e.errors())
    # Shows: age is not a valid integer
```

### Pattern 6: Serialization

Use Pydantic's built-in serialization:

```python
# From dict/JSON
data = {
    "workspaces": [
        {
            "name": "app-sre",
            "vault_token_path": "slack/app-sre/token",
            "usergroups": [...]
        }
    ],
    "dry_run": True
}

request = ReconcileRequest.model_validate(data)

# To dict/JSON
output = request.model_dump()
json_str = request.model_dump_json()

# Exclude fields
minimal = request.model_dump(exclude={"dry_run"})
```

### Pattern 7: Testing

Create test objects with type safety:

```python
def test_reconcile_request():
    """Test with fully typed test data."""
    config = UsergroupConfig(
        users=["user1", "user2"],
        channels=["#alerts"],
    )

    usergroup = Usergroup(
        handle="on-call",
        config=config,
    )

    workspace = Workspace(
        name="test-workspace",
        vault_token_path="slack/test/token",
        usergroups=[usergroup],
    )

    request = ReconcileRequest(
        workspaces=[workspace],
        dry_run=True,
    )

    # Type-safe access in tests
    assert request.workspaces[0].name == "test-workspace"
    assert request.workspaces[0].usergroups[0].handle == "on-call"
    assert len(request.workspaces[0].usergroups[0].config.users) == 2
```

### Pattern 8: When to Use Dicts

Use dicts ONLY for truly dynamic/arbitrary data:

```python
# ✅ OK: Arbitrary metadata (unknown keys)
class Resource(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str
    labels: dict[str, str]  # ← Unknown keys, OK for dicts

# ✅ OK: Dynamic configuration (varies by type)
class Plugin(BaseModel):
    model_config = ConfigDict(frozen=True)
    type: str
    config: dict[str, Any]  # ← Varies by type, OK for dicts

# ❌ AVOID: Known structure
class Usergroup(BaseModel):
    model_config = ConfigDict(frozen=True)
    handle: str
    config: dict[str, Any]  # ← Known structure, use model instead!
```

## References

- Related ADRs: ADR-011 (Dependency Injection Pattern)
- Implementation: `qontract_api/integrations/slack_usergroups/models.py`
- Pydantic documentation: [Models](https://docs.pydantic.dev/latest/concepts/models/)
- FastAPI integration: [Request Body](https://fastapi.tiangolo.com/tutorial/body/)

---

## Notes

**Performance Impact:**

Pydantic model validation adds minimal overhead (~0.1-1ms per request). This is negligible compared to:

- API calls to external services (100-500ms)
- Database queries (10-100ms)
- Network I/O (5-50ms)

The type safety and validation benefits far outweigh the tiny performance cost.

**Migration Strategy:**

For existing code using dicts:

1. Define Pydantic models for the structure
2. Add `.model_validate()` at API boundaries
3. Update internal code to use models
4. Remove dict type hints

Example:

```python
# Before
def process_data(data: dict[str, Any]) -> None:
    name = data["name"]  # Runtime error if missing!
    items = data.get("items", [])

# After
def process_data(data: MyModel) -> None:
    name = data.name  # Guaranteed to exist
    items = data.items  # Type-safe list
```
