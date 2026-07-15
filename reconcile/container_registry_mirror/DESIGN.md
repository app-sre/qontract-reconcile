# Container Registry Mirror Module Design

## Purpose

This module provides a generic container registry mirroring framework.
Specific implementations (Quay, GCP) register themselves and fill in
the details of credential resolution, mirror discovery, and skip logic.
The shared tag sync algorithm lives in the engine and does not need to
be duplicated per destination type.

## Golang Analogy

The design follows the same pattern as
[managed-cluster-validating-webhooks](https://github.com/lisa/managed-cluster-validating-webhooks/tree/master/pkg/webhooks),
adapted to Python idioms.

| Go concept                                                                                                                              | Python equivalent                                                 |
| --------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------- |
| `Webhook` interface in [register.go](https://github.com/lisa/managed-cluster-validating-webhooks/blob/master/pkg/webhooks/register.go)  | `ContainerRegistryMirror` Protocol in `protocol.py`               |
| `var Webhooks = RegisteredWebhooks{}`                                                                                                   | `_registry: dict[str, MirrorFactory]` in `__init__.py`            |
| `func Register(name, factory)`                                                                                                          | `def register(name, factory)` in `__init__.py`                    |
| `func init()` in [add\_pod.go](https://github.com/lisa/managed-cluster-validating-webhooks/blob/master/pkg/webhooks/add_pod.go)         | Module-level `register()` call at bottom of `quay.py` / `gcp.py`  |
| `PodWebhook` struct in [pod/pod.go](https://github.com/lisa/managed-cluster-validating-webhooks/blob/master/pkg/webhooks/pod/pod.go)    | `QuayMirror` class in `quay.py`                                   |
| No equivalent (webhooks don't share logic)                                                                                              | `MirrorEngine` class in `engine.py`                               |

In Go, each webhook implementation satisfies the `Webhook` interface by
implementing the required methods. The main program interacts with all
webhooks generically through the interface. The same holds here: each
mirror implementation satisfies `ContainerRegistryMirror` by
implementing four methods. The engine interacts with all implementations
generically through the protocol.

The key difference: Go enforces interface satisfaction at compile time.
Python's `Protocol` is checked by type checkers (mypy/pyright) at
analysis time, not at runtime. A class satisfies the protocol by
implementing the methods, without declaring that it does so.

## Directory Structure

```text
reconcile/container_registry_mirror/
    __init__.py              # Registry (like register.go)
    protocol.py              # Interface definition (like the Webhook interface)
    engine.py                # Shared tag sync algorithm
    mirror_spec.py           # Data types shared across implementations
    quay.py                  # Quay implementation (like pod/pod.go)
    gcp.py                   # GCP implementation (like scc/scc.go)
```

## Protocol (the Interface)

Defined in `protocol.py`. Any class that implements these four methods
satisfies `ContainerRegistryMirror` without declaring inheritance.

### `resolve_source_credentials`

Fetch read credentials for the source registry and return them in
skopeo's `"user:password"` format. Handles any encoding or decoding
specific to the credential storage (e.g., base64 for GCP service
account keys). Returns `None` for public sources that require no
authentication.

### `resolve_destination_credentials`

Fetch write credentials for the destination registry and return them
in skopeo's `"user:password"` format. The key parameter identifies
which destination (e.g., an `OrgKey` for Quay, a project name for
GCP). By the time this method returns, any storage-specific encoding
(such as base64) has been resolved to plain text.

### `should_skip_mirror`

Determine whether a specific mirror should be skipped. Inputs include
the source registry hostname, source URL, destination URL, and whether
the destination is public. The Quay implementation uses this to block
`docker.io` sources from being mirrored to public repositories (a
security control: Docker Hub images pulled via authenticated mirror
credentials could be re-exposed to the public internet). Implementations
that have no skip conditions return `False`.

### `discover_mirrors`

Query app-interface (or another data source) to determine what should
be mirrored and to where. Each implementation knows its own GraphQL
queries and schema structure. Returns a list of `MirrorSpec` instances
with credentials already resolved to plain `"user:password"` strings.

## Data Types

Defined in `mirror_spec.py`.

### `MirrorSpec`

A single mirror relationship: copy matching tags from source to
destination. By the time this object reaches the engine, all
credentials are resolved to plain `"user:password"` strings.

```python
@dataclass
class MirrorSpec:
    source_url: str
    source_creds: str | None
    destination_url: str
    destination_creds: str
    tag_include: list[str] | None = None
    tag_exclude: list[str] | None = None
```

## Registry

Defined in `__init__.py`. A module-level dict maps implementation names
to factory functions. This is the Python equivalent of Go's
`var Webhooks = RegisteredWebhooks{}` and `func Register()`.

```python
MirrorFactory = Callable[[], ContainerRegistryMirror]

_registry: dict[str, MirrorFactory] = {}

def register(name: str, factory: MirrorFactory) -> None: ...
def get_mirror(name: str) -> ContainerRegistryMirror: ...
def registered_mirrors() -> dict[str, MirrorFactory]: ...
```

Each implementation module registers itself with a module-level
`register()` call at the bottom of the file, equivalent to Go's
`func init()` in files like `add_pod.go`:

```python
# At the bottom of quay.py
register("quay-mirror", lambda: QuayMirror())
```

## Engine (Shared Algorithm)

Defined in `engine.py`. The Go webhook example has no equivalent
because each webhook's `Authorized()` method is fully independent.
The mirror case is different: the tag sync algorithm is identical
across implementations. The engine consumes `list[MirrorSpec]` and
runs the shared loop.

The engine is responsible for:

* Building `Image` objects for source and destination
* Iterating source tags and filtering via include/exclude patterns
* Checking tag existence at the destination (fast path)
* Comparing manifests when deep sync is active (slow path)
* Handling multi-arch images (`is_part_of`) and comparison errors
* Copying via skopeo with error aggregation
* Recording the deep sync timestamp after successful completion

The engine does not know where specs came from. It does not query
GraphQL. It does not read Vault. It receives `MirrorSpec` instances
and syncs them.

## Implementations

### `quay.py` (Quay Mirror)

Mirrors images from any source registry into Quay organisations.

* `resolve_source_credentials`: reads from Vault via `SecretReader`,
  returns plain `"user:token"`
* `resolve_destination_credentials`: looks up pre-fetched push
  credentials by `OrgKey`
* `should_skip_mirror`: blocks `docker.io` sources to public Quay
  repos
* `discover_mirrors`: queries `quay_repos` from app-interface via
  `queries.get_quay_repos()`

### `gcp.py` (GCP Mirror)

Mirrors images from any source registry into GCR or Artifact Registry.

* `resolve_source_credentials`: reads from Vault via `SecretReader`,
  returns plain `"user:token"` (identical to Quay)
* `resolve_destination_credentials`: looks up pre-fetched push
  credentials by project name with `gcr_` or `ar_` prefix (the
  base64 decode of GCP service account keys happens at init time,
  not here)
* `should_skip_mirror`: returns `False` (GCP schema has no public
  flag)
* `discover_mirrors`: queries `gcp_docker_repos` from app-interface
  via generated Pydantic query modules

## Why the Credentials Are Not a Separate Abstraction

Both Quay and GCP resolve credentials to the same format:
`"user:password"`. The only difference is that GCP base64-decodes the
token from Vault, while Quay uses it as-is. This decode happens once
during `_get_push_creds()` at init time. By the time
`resolve_destination_credentials()` is called, both implementations
return a plain string. A separate `PushCredentials` abstraction would
add a layer of indirection for a one-line difference.

## Related Files

* `reconcile/utils/quay_mirror.py`: shared utilities
  (`record_timestamp`, `sync_tag`). Used by the engine.
* `reconcile/quay_mirror_org.py`: a separate integration that
  mirrors between Quay orgs using Quay API enumeration rather
  than app-interface config. Uses `DeepSyncTimer` from this
  module but does not use the engine or protocol (it has its
  own sync logic tied to `QuayApiStore`).
* `reconcile/cli.py`: imports `reconcile.container_registry_mirror.quay`
  and `reconcile.container_registry_mirror.gcp` directly as
  integration modules.
