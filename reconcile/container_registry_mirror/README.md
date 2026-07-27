# Container Registry Mirror

This module provides a framework for mirroring container images between
registries. The tag sync algorithm (enumerate source tags, filter,
check existence at the destination, compare manifests, copy via skopeo)
is implemented once in the engine. Each destination type (Quay, GCP)
provides an implementation that handles its own credential resolution
and mirror discovery.

## How It Works

A mirror operation has three steps:

1. An implementation discovers what needs to be mirrored by querying
   app-interface (or another data source) and produces a list of
   `MirrorSpec` objects. Each spec contains a source URL, a destination
   URL, resolved credentials for both, and optional tag filter patterns.

2. The engine receives the list of specs and runs the tag sync
   algorithm. For each spec, it enumerates tags at the source,
   filters them, checks whether each tag exists at the destination,
   optionally compares manifests (deep sync), and copies any
   out-of-sync images using skopeo.

3. Copy failures are collected and raised as an `ExceptionGroup`
   after all specs are processed, so that one broken mirror does not
   prevent the rest from syncing.

## Module Structure

### [protocol.py](protocol.py)

Defines `ContainerRegistryMirror`, the interface that each destination
implementation must satisfy. Any class that implements the four required
methods satisfies the protocol without needing to declare inheritance.
Type checkers (mypy, pyright) enforce this at analysis time.

### [mirror_spec.py](mirror_spec.py)

Defines `MirrorSpec`, a dataclass representing a single mirror
relationship. By the time a `MirrorSpec` reaches the engine, all
credentials are resolved to plain `"user:password"` strings. The
engine does not know how they were obtained.

#### Attributes

* `source_url` (`str`): the full image URL at the source registry
  (e.g., `docker.io/library/nginx`).
* `source_creds` (`str | None`): pull credentials for the source
  registry in `"user:password"` format. `None` for public sources.
* `destination_url` (`str`): the full image URL at the destination
  registry (e.g., `quay.io/org/nginx` or
  `gcr.io/my-project/nginx`).
* `destination_creds` (`str`): push credentials for the destination
  registry in `"user:password"` format.
* `tag_include` (`list[str] | None`): regex patterns controlling
  which tags are mirrored. Only tags matching at least one pattern
  are synced. `None` means all tags are eligible. Operators use this
  to limit mirroring to specific tag conventions (e.g.,
  `["^v[0-9]+"]` for semver releases only).
* `tag_exclude` (`list[str] | None`): regex patterns controlling
  which tags are excluded from mirroring. Tags matching any pattern
  are skipped. `None` means no tags are excluded. Operators use this
  to filter out unwanted tags (e.g., `["^sha256-.+sig$"]` for cosign
  signatures that should not be mirrored). When both `tag_include`
  and `tag_exclude` are set, exclusions take precedence: a tag that
  matches both an include and an exclude pattern is skipped.

### [deep\_sync\_timer.py](deep_sync_timer.py)

Contains `DeepSyncTimer`, which controls when the engine runs
expensive manifest comparisons. Routine sync runs only mirror tags
that are missing at the destination. Periodically, a deep sync
fetches and compares manifests to detect drift on mutable tags. The
timer reads a timestamp from a control file, compares the elapsed
time to a configurable interval, and decides whether the current run
should be a deep sync. After a successful deep sync, the engine
calls `timer.record()` to write the current timestamp.

The timer also supports a CLI override (`--compare-tags` /
`--no-compare-tags`) that bypasses the interval logic entirely,
used for debugging or incident response.

The `from_dir` classmethod constructs a timer with the control file
path resolved from a directory and filename. Using a persistent
directory (e.g., a Kubernetes mounted volume) allows the timestamp
to survive pod restarts, preventing unnecessary slow runs after
redeployment.

### [engine.py](engine.py)

Contains `MirrorEngine`, which implements the shared tag sync
algorithm. The engine accepts a skopeo instance, a dry-run flag, and
optionally a `DeepSyncTimer`. When a timer is provided, the engine
consults it to decide whether manifest comparisons should run and
records the timestamp after a successful deep sync. It does not
query GraphQL, read Vault, or know anything about the destination
type.

### [\_\_init\_\_.py](__init__.py)

Provides the implementation registry: `register()`, `get_mirror()`,
and `registered_mirrors()`. Each implementation registers itself at
import time by calling `register()` at the bottom of its module.

### [quay.py](quay.py)

Quay destination implementation. Discovers mirrors from app-interface's
`quay_repos` GraphQL query, resolves credentials from Vault via
`SecretReader`, and blocks `docker.io` sources from being mirrored to
public Quay repositories. Also contains the integration framework
entry points (`QONTRACT_INTEGRATION`, `run()`,
`early_exit_desired_state()`) and constructs the `DeepSyncTimer` and
`InstrumentedSkopeo` for the quay-mirror integration. `cli.py`
imports this module directly.

### [gcp.py](gcp.py)

GCP destination implementation. Discovers mirrors from app-interface's
`gcp_docker_repos` GraphQL query, resolves credentials from Vault via
`SecretReader` with base64 decoding (GCP service account keys are
stored base64-encoded in Vault), and supports both GCR and Artifact
Registry destinations. Also contains the integration framework entry
points (`QONTRACT_INTEGRATION`, `run()`) and constructs the
`InstrumentedSkopeo` for the gcp-image-mirror integration. `cli.py`
imports this module directly.

## The Interface

The `ContainerRegistryMirror` protocol requires four methods.

### `resolve_source_credentials`

```python
def resolve_source_credentials(
    self, secret_ref: dict[str, Any] | None,
) -> str | None:
```

Read credentials for the source registry and return them in skopeo's
`"user:password"` format. Return `None` for public sources that
require no authentication. Handle any encoding specific to the
credential storage (e.g., base64 decoding for GCP service account
keys stored in Vault).

### `resolve_destination_credentials`

```python
def resolve_destination_credentials(self, key: str) -> str:
```

Read credentials for the destination registry and return them in
skopeo's `"user:password"` format. The `key` parameter identifies
which destination (e.g., an org key for Quay, a project name for GCP).
By the time this method returns, any storage-specific encoding has
been resolved to plain text.

### `should_skip_mirror`

```python
def should_skip_mirror(
    self,
    source_registry: str,
    source_url: str,
    destination_url: str,
    destination_public: bool | None,
) -> bool:
```

Determine whether a specific mirror should be skipped. Return `True`
to skip, `False` to proceed. This is where destination-specific
validation rules go. For example, the Quay implementation blocks
`docker.io` sources from being mirrored to public repositories
because the mirrored images could re-expose private content to the
public internet. Implementations with no skip conditions return
`False`.

### `discover_mirrors`

```python
def discover_mirrors(self) -> list[MirrorSpec]:
```

Query app-interface (or another data source) to determine what should
be mirrored and to where. Each implementation knows its own GraphQL
queries and schema structure. Return a list of `MirrorSpec` instances
with credentials already resolved to plain `"user:password"` strings.

## When to Add a New Destination

A new implementation is needed when the destination registry requires
different handling for any of these concerns:

### Credential format

Skopeo always receives credentials as `"user:password"`. If the new
destination stores credentials differently in Vault (e.g., base64
encoded, JSON key file, OAuth token exchange), the implementation's
`resolve_destination_credentials` must handle the conversion. The
existing implementations demonstrate two patterns:

* **Quay**: Vault stores `user` and `token` as plain strings. No
  post-processing. `resolve_destination_credentials` returns
  `f"{user}:{token}"` directly.

* **GCP**: Vault stores `user` as a plain string and `token` as a
  base64-encoded GCP service account key. `_get_push_creds()` calls
  `base64.b64decode(token)` at init time. By the time
  `resolve_destination_credentials` is called, the value is already
  plain text.

If the new destination's credentials can be resolved to
`"user:password"` using the same logic as an existing implementation,
a new implementation is not needed; the existing one can be reused.

### Mirror discovery

If the new destination's mirror definitions are stored under a
different schema in app-interface (a different GraphQL query,
different data structure), the implementation needs its own
`discover_mirrors` method. The Quay implementation reads from
`quay_repos`; the GCP implementation reads from `gcp_docker_repos`.

### Validation rules

If the new destination has restrictions on which sources can be
mirrored (analogous to the Quay docker.io-to-public block), the
implementation provides those rules in `should_skip_mirror`. If no
restrictions apply, the method returns `False`.

## Adding a New Destination

### Step 1: Create the implementation

Create a new file in this directory (e.g., `ecr.py` for Amazon ECR).
The class must implement the four protocol methods. The file must
also contain the integration framework entry points
(`QONTRACT_INTEGRATION` and a module-level `run()` function) because
`cli.py` imports the module directly. Use [quay.py](quay.py) or
[gcp.py](gcp.py) as a reference.

```python
from reconcile.container_registry_mirror import register
from reconcile.container_registry_mirror.engine import MirrorEngine
from reconcile.container_registry_mirror.mirror_spec import MirrorSpec
from reconcile.utils.instrumented_wrappers import InstrumentedSkopeo as Skopeo


class EcrMirror:
    def __init__(self) -> None:
        # Set up gqlapi, secret_reader, and pre-fetch push credentials.
        ...

    def resolve_source_credentials(self, secret_ref, ...) -> str | None:
        ...

    def resolve_destination_credentials(self, key) -> str:
        ...

    def should_skip_mirror(self, ...) -> bool:
        ...

    def discover_mirrors(self) -> list[MirrorSpec]:
        ...


register("ecr-mirror", EcrMirror)

QONTRACT_INTEGRATION = "ecr-mirror"


def run(dry_run: bool) -> None:
    impl = EcrMirror()
    specs = impl.discover_mirrors()
    engine = MirrorEngine(
        skopeo=Skopeo(dry_run),
        dry_run=dry_run,
    )
    engine.sync(specs)
```

### Step 2: Write tests

Create `reconcile/test/test_container_registry_mirror/test_ecr.py`.
Test each protocol method independently:

* `discover_mirrors` transforms GraphQL data into `MirrorSpec` list
* `resolve_source_credentials` handles both `None` and present
  credentials
* `resolve_destination_credentials` returns the correct format for
  the destination
* `should_skip_mirror` enforces any destination-specific rules
* `run()` constructs the engine and calls `sync()` (mock the engine)

### Step 3: Register in the CLI

Add a CLI command in `reconcile/cli.py` that imports the new module
and passes it to `run_integration()`:

```python
@integration.command(short_help="Mirrors external images into ECR.")
@click.pass_context
@binary(["skopeo"])
def ecr_mirror(ctx: click.Context) -> None:
    import reconcile.container_registry_mirror.ecr

    run_integration(reconcile.container_registry_mirror.ecr, ctx)
```
