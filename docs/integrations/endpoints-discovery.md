# endpoints-discovery

**Last Updated:** 2026-11-24

## Description

Reconciles the `endPoints` list of App-Interface application files with the OpenShift Routes that actually exist on their clusters. The integration discovers routes namespace by namespace, renders new endpoint entries from an App-Interface template, and opens a single app-interface merge request containing every changed application file. It never writes to clusters.

## Features

* Discover OpenShift Routes across clusters and add missing `endPoints` entries
* Update an endpoint when a route's host or TLS setting changes
* Delete managed endpoints for namespaces that were removed or marked `delete: true`
* Honour per-route ignore labels from application and namespace labels
* Keep at most one merge request for all applications, closing stale, malformed or conflicted ones
* Plan-and-apply with dry-run as the default

## Desired State Details

The desired state is inverted relative to most integrations: the live cluster is the source of truth for routes, while App-Interface supplies the current `endPoints`, the namespace set, and the rendering template.

Applications are read from `apps_v1` with:

* `name`, `path`, `labels`
* `endPoints`: the currently declared endpoints (`name`, `url`)
* `namespaces`: `name`, `labels`, `delete`, and the cluster connection from the `OcConnectionCluster` fragment

Endpoints managed by this integration follow a fixed naming convention:

```text
endpoints-discovery/<cluster>/<namespace>/<sorted route names joined by |>
```

Routes sharing a host and TLS flag are merged into one endpoint, which is why the name can contain several route names. The URL is derived as `host:443` for TLS routes and `host:80` otherwise. Any endpoint whose name does not match the convention is treated as manual and left untouched.

The ignore label key is `endpoints-discovery-<route names>`, for example `endpoints-discovery-route-a|route-b`. Application labels are merged with namespace labels, with namespace labels winning on conflict.

## Architecture

**Client-Side (reconcile/endpoints_discovery_api.py):**

* Fetches applications and namespaces from App-Interface (GraphQL)
* Applies `--app-name`, `--cluster-name` and `--internal` filters
* Marks each namespace with a `discover` flag. Filtered and disabled namespaces are sent with `discover=false` so their endpoints are preserved and no cluster connection is required. Deleted namespaces are also sent with `discover=false`, purely to skip discovery; their managed endpoints are deleted regardless of the flag
* Selects one automation token reference per cluster, preferring the active rotation-aware list entry over the legacy `automationToken`
* Fetches the endpoint template resource and the app-interface repository token reference
* Resolves the auto-merge toggle and sends the request
* In dry-run: polls the task and logs each planned action
* In non-dry-run: fires and forgets; events are published server-side

**Server-Side (qontract_api/integrations/endpoints_discovery/):**

* Reads cluster automation tokens from Vault and validates the secret's `server` against the cluster `serverUrl`
* Lists routes per namespace through lightkube (Layer 1), uncached
* Groups routes by host and TLS, filters ignored routes, and diffs against the supplied current endpoints using `diff_any_iterables`, comparing URLs only
* Renders add and change entries from the template
* Reads each changed application file from git, merges the `endPoints` list with a ruamel round-trip, and skips files whose content would not change
* Deduplicates the merge request from the machine-readable hash in its description, closing stale or invalid MRs
* Creates one merge request with one update operation per changed application

## API Endpoints

### Queue Reconciliation Task

```http
POST /api/v1/integrations/endpoints-discovery/reconcile
Authorization: Bearer <JWT_TOKEN>
Content-Type: application/json
```

**Request Body:**

```json
{
  "endpoint_template": "name: {{ endpoint_name }}\nurl: {{ route.url }}\n",
  "app_interface": {
    "repo_url": "https://gitlab.example.com/service/app-interface",
    "token": {
      "secret_manager_url": "https://vault.example.com",
      "path": "app-sre/app-interface-token",
      "field": "token"
    },
    "target_branch": "master"
  },
  "apps": [
    {
      "name": "rbac",
      "path": "/services/insights/rbac/app.yml",
      "labels": {},
      "end_points": [
        {"name": "manual-endpoint", "url": "manual.example.com:443"}
      ],
      "namespaces": [
        {
          "name": "rbac-stage",
          "labels": {},
          "delete": false,
          "discover": true,
          "cluster": {
            "cluster_name": "crcs02ue1",
            "server_url": "https://api.crcs02ue1.example.com:6443",
            "automation_token": {
              "secret_manager_url": "https://vault.example.com",
              "path": "app-sre/clusters/crcs02ue1",
              "field": "token"
            },
            "insecure_skip_tls_verify": false,
            "internal": false,
            "disabled_integrations": []
          }
        }
      ]
    }
  ],
  "auto_merge": false,
  "dry_run": true
}
```

**Response:** (202 Accepted)

```json
{
  "id": "uuid-string",
  "status": "pending",
  "status_url": "/api/v1/integrations/endpoints-discovery/reconcile/{task_id}"
}
```

### Get Task Result

```http
GET /api/v1/integrations/endpoints-discovery/reconcile/{task_id}?timeout=30
Authorization: Bearer <JWT_TOKEN>
```

**Query Parameters:**

* `timeout` (optional): Block up to N seconds for completion (default: None = immediate status)

**Response:**

```json
{
  "status": "success",
  "actions": [
    {
      "action_type": "add_endpoint",
      "app_name": "rbac",
      "app_path": "/services/insights/rbac/app.yml",
      "cluster": "crcs02ue1",
      "namespace": "rbac-stage",
      "endpoint_name": "endpoints-discovery/crcs02ue1/rbac-stage/gabi-rbac",
      "data": {
        "name": "endpoints-discovery/crcs02ue1/rbac-stage/gabi-rbac",
        "url": "gabi-rbac-stage.apps.crcs02ue1.example.com:443"
      }
    }
  ],
  "applied_actions": [],
  "applied_count": 0,
  "apps_with_changes": 1,
  "mr_status": null,
  "mr_url": null,
  "errors": []
}
```

### Models

**Request Fields:**

| Field               | Type               | Required | Default | Description                                                     |
| ------------------- | ------------------ | -------- | ------- | --------------------------------------------------------------- |
| `endpoint_template` | `string`           | Yes      | -       | Jinja2 template content from the App-Interface resource         |
| `app_interface`     | `AppInterfaceRepo` | Yes      | -       | Repository URL, token reference, target branch                  |
| `apps`              | `list[DesiredApp]` | Yes      | -       | Applications with namespaces and current endpoints              |
| `auto_merge`        | `bool`             | No       | `false` | Add the `bot/automerge` label to the merge request              |
| `dry_run`           | `bool`             | No       | `true`  | If true, only calculate actions without opening a merge request |

Namespace fields of note:

* `discover`: whether the server should read routes. `false` preserves existing endpoints and needs no cluster connection. `delete: true` takes precedence: the namespace's endpoints are removed even when `discover` is true.
* `delete`: the namespace is being removed; its endpoints are deleted.
* `cluster.automation_token`: required only when `discover` is true. The secret must contain a `server` entry matching `server_url`.

**Validation Rules:**

* A discovered namespace without an automation token fails the run before any request is sent.
* The secret's `server` field must equal the cluster `server_url`; a mismatch is a per-cluster error.
* Both `endpoints-discovery-api` and `endpoints-discovery` are checked against `cluster.disable.integrations`.
* An application file that cannot be read fails the run without opening a partial merge request.

**Response Fields:**

| Field               | Type                    | Description                                                       |                                                                |
| ------------------- | ----------------------- | ----------------------------------------------------------------- |                                                                |
| `status`            | `TaskStatus`            | Task execution status (pending/success/failed)                    |                                                                |
| `actions`           | `list[EndpointAction]`  | Planned endpoint changes                                          |                                                                |
| `applied_actions`   | `list[EndpointAction]`  | Actions whose content reached a newly created merge request       |                                                                |
| `applied_count`     | `int`                   | Number of applied actions (0 in dry-run)                          |                                                                |
| `apps_with_changes` | `int`                   | Applications with at least one change, matching legacy reporting  |                                                                |
| `mr_status`         | `string \               | null`                                                             | `created`, `exists`, `closed_outdated`, `not_needed`, `failed` |
| `mr_url`            | `string \               | null`                                                             | URL of the created or existing merge request                   |
| `errors`            | `list[string]`          | Errors encountered during reconciliation                          |                                                                |

The integration can perform these reconciliation actions:

`add_endpoint`:

**Description:** Add an endpoint rendered from the template.

**Fields:**

* `app_name`, `app_path`: owning application
* `cluster`, `namespace`: source of the route
* `endpoint_name`: the new endpoint name
* `data`: the rendered endpoint mapping

**Example:**

```json
{
  "action_type": "add_endpoint",
  "app_name": "rbac",
  "app_path": "/services/insights/rbac/app.yml",
  "cluster": "crcs02ue1",
  "namespace": "rbac-stage",
  "endpoint_name": "endpoints-discovery/crcs02ue1/rbac-stage/gabi-rbac",
  "data": {"name": "endpoints-discovery/crcs02ue1/rbac-stage/gabi-rbac", "url": "gabi-rbac-stage.apps.crcs02ue1.example.com:443"}
}
```

`change_endpoint`:

**Description:** Replace an existing endpoint in place with newly rendered content. `endpoint_name` is the current name, while `data.name` may differ when the route name set changed.

**Fields:** the same as `add_endpoint`, with `endpoint_name` identifying the existing entry.

`delete_endpoint`:

**Description:** Delete an endpoint that no longer corresponds to a route, a namespace, or the application configuration.

**Fields:**

* `app_name`, `app_path`
* `endpoint_name`
* `cluster`, `namespace`: parsed from the endpoint name when possible, otherwise null

**Example:**

```json
{
  "action_type": "delete_endpoint",
  "app_name": "rbac",
  "app_path": "/services/insights/rbac/app.yml",
  "endpoint_name": "endpoints-discovery/crcs02ue1/rbac-stage/gabi-rbac",
  "cluster": "crcs02ue1",
  "namespace": "rbac-stage"
}
```

## Limits and Constraints

**Safety:**

* `dry_run` defaults to `true`; the CLI can never create a merge request unless the scheduler runs it live.
* A namespace that cannot be read produces no endpoint actions for that namespace. No deletions are derived from an incomplete read.
* A namespace that is definitively absent yields no routes, so its managed endpoints are deleted, matching the previous integration.
* Filtered, deleted and disabled namespaces still travel in the payload so cleanup never mistakes filtering for removal.
* An application file whose merged content equals its current content produces no commit.

**Managed Resources:**

* Only endpoints whose names start with `endpoints-discovery/<cluster>/<namespace>/` are managed. Manual endpoints are never modified.
* Only the URL is compared. `description`, `monitoring` and other template fields are owned by the template and are not reconciled.
* Only routes are read. The integration never writes to clusters.

**Merge Requests:**

* One merge request exists for all applications at a time.
* The description carries `integration`, `endpoints-discovery-version: 1.0.0` and a content hash below a separator line.
* An open merge request with a matching hash is a no-op. A different hash closes it, and a replacement opens on the next run so a disabled deletion cannot leave two open MRs.
* An error-free empty plan still inspects open MRs and closes one built from an earlier plan. Incomplete planning leaves merge request state untouched, because a partial read is not proof that an MR is obsolete.
* An addition whose name already exists in the file is skipped when the content is identical, and fails the run when the content differs, so stale GraphQL never writes duplicate endpoints.
* Merge requests with conflicts, a version mismatch or an unparseable description are closed and replaced in the same run.
* Title and label are fixed at `[auto] endpoints-discovery: update application endpoints` and `ENDPOINTS-DISCOVERY`.
* Only GitLab supports mutation. GitHub raises `NotImplementedError`.

**Rate Limiting and Caching:**

* Kubernetes route listing and namespace checks are uncached, because they are the current state being reconciled.
* Redis provides task deduplication; live runs share the constant lock key `endpoints-discovery`.
* Vault reads are cached briefly by the secret manager. Cluster token resolution is limited to clusters with at least one `discover=true` namespace.

**Other Constraints:**

* Sharding is not supported, because an application can have endpoints in several clusters.
* Extended early exit is not carried over from the legacy integration.
* Endpoint rendering uses a sandboxed Jinja environment; underscore attributes are not reachable from templates.

## Required Components

**Vault Secrets:**

* Cluster automation tokens: JSON secrets containing `server`, `username` and a token field. The token reference's `field` must be set.
* App-interface repository token: read access to application files and write access to branches and merge requests.

**External APIs:**

* Kubernetes/OpenShift API per cluster
  * Authentication: bearer token from the automation token secret
  * `route.openshift.io/v1` Routes and Namespaces
* GitLab API for the app-interface project
  * Authentication: repository token
  * Branches, files, merge requests

**Cache Backend:**

* Redis/Valkey required for task deduplication and VCS provider caching

**App-Interface Resources:**

* `/endpoints-discovery/endpoint-template.yml` (or the path passed with `--endpoint-tmpl-resource`)

## Configuration

**App-Interface Schema:**

Namespace and endpoint configuration lives in the application file:

```yaml
$schema: /app-sre/app-1.yml
name: rbac
endPoints:
  - name: endpoints-discovery/crcs02ue1/rbac-stage/gabi-rbac
    description: Managed by endpoints-discovery
    url: gabi-rbac-stage.apps.crcs02ue1.example.com:443
namespaces:
  - $ref: /services/insights/rbac/namespaces/rbac-stage.yml
```

Namespace ignore labels look like:

```yaml
labels:
  endpoints-discovery-gabi-rbac: ignored
```

**Integration Settings:**

| Setting           | Source                                             | Default                                      | Description                             |
| ----------------- | -------------------------------------------------- | -------------------------------------------- | --------------------------------------- |
| Template resource | `--endpoint-tmpl-resource`                         | `/endpoints-discovery/endpoint-template.yml` | Resource rendered into each endpoint    |
| Auto-merge        | Unleash `endpoints-discovery-allow-auto-merge-mrs` | `false`                                      | Adds the `bot/automerge` label          |
| Enablement        | Unleash `endpoints-discovery-api`                  | enabled                                      | Standard client-side integration toggle |
| Target branch     | request `app_interface.target_branch`              | `master`                                     | Merge request target                    |

Deployment uses the app-interface integration file `qontract-reconcile-endpoints-discovery-api.yml` with `extraArgs: --endpoint-tmpl-resource /endpoints-discovery/endpoint-template.yml` and a `sleepDurationSecs` of `600`.

## Client Integration

**File:** [reconcile/endpoints_discovery_api.py](../../reconcile/endpoints_discovery_api.py)

**CLI Command:** `qontract-reconcile endpoints-discovery-api`

**Arguments and Options:**

* `--internal/--external`: restrict to internal or external clusters
* `--cluster-name`: repeatable cluster filter
* `--app-name`: consider a single application
* `--endpoint-tmpl-resource`: App-Interface resource holding the endpoint template

**Client Architecture:**

* GraphQL is the only direct data source. Route discovery and git access are server-side.
* The app-interface repository token is matched to `vcs_instances` by URL prefix and sent as a reference.
* All non-deleted namespaces are sent, each with a `discover` flag, so a filtered run preserves excluded endpoints.
* Dry-run raises on task timeouts and reported errors; live runs return immediately after queueing.

## Troubleshooting

### Issue 1: No merge request opens and `mr_status` is `exists`

* **Symptom:** Actions are calculated but no new MR appears.
* **Cause:** An open MR has a matching content hash.
* **Solution:** Merge the existing MR. Closing it without merging does not stop the cycle: while the plan is unchanged, the next reconciliation opens a replacement MR with the same hash.

### Issue 2: `mr_status` is `closed_outdated` and nothing replaced it

* **Symptom:** The stale MR is closed but no replacement appears in the same run.
* **Cause:** Intentional, so a deployment with MR deletion disabled cannot accumulate MRs.
* **Solution:** Wait for the next scheduled run.

### Issue 3: Run fails on a cluster token

* **Symptom:** `Failed to read token for cluster ...` or a server URL mismatch error.
* **Cause:** Missing `automationToken`, missing `field`, or the secret's `server` no longer matches the cluster.
* **Solution:** Fix the cluster's token configuration. Other clusters still plan, but the run reports failure.

### Issue 4: Endpoints were deleted unexpectedly

* **Symptom:** A namespace loses managed endpoints.
* **Cause:** The namespace was removed from the application, marked `delete: true`, or is definitively absent from the cluster.
* **Solution:** Confirm the namespace is still intended to exist. Read errors never delete, so a transient API failure is not the cause.

### Issue 5: Endpoints under a filtered namespace were not updated

* **Symptom:** A run with `--cluster-name` or `--internal` leaves some endpoints unchanged.
* **Cause:** Excluded namespaces are sent with `discover=false`.
* **Solution:** Run without the filter to discover those namespaces.

### Issue 6: Application file reported as missing

* **Symptom:** `file ... is missing or unreadable on master; no merge request opened`.
* **Cause:** qontract-server data can lag behind the repository, or the token lacks read access.
* **Solution:** The next run usually resolves the lag. Check token access if it persists.

## References

**Code:**

* Server: [qontract_api/qontract_api/integrations/endpoints_discovery/](../../qontract_api/qontract_api/integrations/endpoints_discovery/)
* Client: [reconcile/endpoints_discovery_api.py](../../reconcile/endpoints_discovery_api.py)
* GraphQL query: [reconcile/gql_definitions/endpoints_discovery_api/apps.gql](../../reconcile/gql_definitions/endpoints_discovery_api/apps.gql)
* Shared VCS layer: [qontract_api/qontract_api/vcs/](../../qontract_api/qontract_api/vcs/)

**Architecture:**

* [ADR-002: Client-Side GraphQL Fetching Only](../adr/ADR-002-client-side-graphql-fetching.md)
* [ADR-008: Qontract-API Client Integration Pattern](../adr/ADR-008-qontract-api-client-integration-pattern.md)
* [ADR-013: Centralize External API Calls](../adr/ADR-013-centralize-external-api-calls.md)
* [ADR-014: Three-Layer Architecture](../adr/ADR-014-three-layer-architecture-for-external-apis.md)

**Legacy Implementation:**

* [reconcile/endpoints_discovery/](../../reconcile/endpoints_discovery/)
