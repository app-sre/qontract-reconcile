# ldap-users-api

**Last Updated:** 2026-04-27

## Description

Removes users from app-interface and infra repositories when they no longer exist in LDAP (FreeIPA). This integration replaces the legacy `ldap-users` integration with a qontract-api-based architecture using the **client-orchestrated pattern** — all business logic runs in the client, with qontract-api providing external endpoints for LDAP lookups and VCS merge request creation.

## Features

- Check user existence in LDAP via qontract-api external endpoint (cached, FreeIPA-authenticated)
- Safety check: abort if LDAP returns empty result set (prevents mass deletion)
- Create per-user MRs in app-interface to delete orphaned user resources
- Create single MR in infra repo to remove users from bastion and admin lists
- MR deduplication by title (prevents duplicate MRs for the same user)
- Auto-merge controlled via Unleash feature toggle
- Configurable MR labels

## Desired State Details

Users are defined in App-Interface with associated resource paths queried via GraphQL:

- **User path** (`/users/<username>.yml`) — the user definition file
- **Requests** (`/access-requests/*.yml`) — credential requests
- **Queries** (`/queries/*.yml`) — SQL query definitions
- **GABI instances** (`/gabi/*.yml`) — GABI instance user lists (YAML modification)
- **AWS accounts** (`/aws/*.yml`) — AWS account reset password entries (YAML modification)
- **Schedules** (`/schedules/*.yml`) — on-call schedule entries (YAML modification)
- **SRE checkpoints** (`/checkpoints/*.yml`) — SRE checkpoint files

LDAP settings (server URL, base DN, credentials) are configured in `app-interface-settings-1.yml` under `ldap.credentials`.

## Architecture

**Architecture Pattern:** Client-Orchestrated (Pattern 2)

Unlike server-side integrations (glitchtip, slack-usergroups), ldap-users performs app-interface-specific actions (YAML file manipulation in GitLab MRs). This logic does not belong in qontract_api.

```text
reconcile/ldap_users_api/          (client - orchestration + business logic)
    │
    ├── GraphQL ──────────────────→ app-interface (users with paths)
    │
    ├── POST /external/ldap/users/check → qontract_api (cached LDAP user check)
    │
    ├── diff locally ─────────────→ (who is missing in LDAP?)
    │
    ├── safety check ─────────────→ (abort if LDAP returned empty)
    │
    ├── GET /external/vcs/merge-requests → dedup check (MR already exists?)
    │
    ├── GET /external/vcs/repos/file ───→ read file for YAML modification
    │
    └── POST /external/vcs/merge-requests → create deletion MRs
```

**No `qontract_api/integrations/ldap_users/`** — no service, router, tasks, or Celery.

**Client-Side (`reconcile/ldap_users_api/`):**

- Fetches users with paths from App-Interface (GraphQL)
- Fetches LDAP settings and VCS instances from App-Interface (GraphQL)
- Checks user existence via `/external/ldap/users/check`
- Computes diff (users in app-interface but not in LDAP)
- Builds file operations for deletion MRs (delete files or modify YAML)
- Creates MRs via `/external/vcs/merge-requests` with deduplication

**Server-Side (external endpoints only):**

- `POST /external/ldap/users/check` — cached LDAP user existence check (FreeIPA)
- `GET /external/vcs/merge-requests` — find existing MR by title (deduplication)
- `GET /external/vcs/repos/file` — read file content for YAML modification
- `POST /external/vcs/merge-requests` — create MR with file operations

## API Endpoints

This integration does not have its own reconciliation endpoint. It uses shared external endpoints:

### Check LDAP Users

```http
POST /api/v1/external/ldap/users/check
Authorization: Bearer <JWT_TOKEN>
Content-Type: application/json
```

**Request Body:**

```json
{
  "usernames": ["alice", "bob"],
  "secret": {
    "secret_manager_url": "https://vault.example.com",
    "path": "app-sre/creds/app-sre-ldap-ipa",
    "server_url": "ldap://freeipa.example.com",
    "base_dn": "dc=example,dc=com"
  }
}
```

**Response:**

```json
{
  "users": [
    {"username": "alice", "exists": true},
    {"username": "bob", "exists": false}
  ]
}
```

### Find Existing MR (Deduplication)

```http
GET /api/v1/external/vcs/merge-requests?repo_url=...&title=...&secret_manager_url=...&path=...&field=...
Authorization: Bearer <JWT_TOKEN>
```

Returns 200 with MR URL if found, 404 if not.

### Create Deletion MR

```http
POST /api/v1/external/vcs/merge-requests
Authorization: Bearer <JWT_TOKEN>
Content-Type: application/json
```

**Request Body:**

```json
{
  "repo_url": "https://gitlab.example.com/service/app-interface",
  "token": {"secret_manager_url": "...", "path": "...", "field": "..."},
  "title": "[create_delete_user_mr] delete user alice",
  "description": "delete user alice",
  "file_operations": [
    {"path": "data/users/alice.yml", "action": "delete", "commit_message": "..."},
    {"path": "data/gabi/instance.yml", "action": "update", "content": "...", "commit_message": "..."}
  ],
  "labels": ["ldap-users"],
  "auto_merge": false
}
```

### Models

**File Operation Actions:**

| Action   | Description                  | Content    |
| -------- | ---------------------------- | ---------- |
| `create` | Create a new file            | Required   |
| `update` | Update existing file content | Required   |
| `delete` | Delete a file                | Not needed |

**Path Types and Actions:**

| Path Type        | Action   | Description                                                  |
| ---------------- | -------- | ------------------------------------------------------------ |
| `user`           | `delete` | Delete the user YAML file                                    |
| `request`        | `delete` | Delete the credential request file                           |
| `query`          | `delete` | Delete the SQL query file                                    |
| `sre_checkpoint` | `delete` | Delete the SRE checkpoint file                               |
| `gabi`           | `update` | Remove user `$ref` from `users[]` list                       |
| `aws_accounts`   | `update` | Remove user from `resetPasswords[]` list                     |
| `schedule`       | `update` | Remove user `$ref` from `schedule[].users[]` (stem matching) |

**Infra Repo User Lists:**

The integration scans infra YAML files for user lists with known name fields (`name`, `login_name`), removes matching entries, and appends to `deleted_users[]`.

## Limits and Constraints

**Safety:**

- Safety check: if LDAP returns zero existing users while app-interface has users, the integration aborts with `RuntimeError` to prevent mass deletion
- `auto_merge` defaults to `false` — controlled via Unleash feature toggle `ldap-users-api-allow-auto-merge-mrs`
- MR deduplication: checks for existing open MRs by title before creating new ones
- Original `reconcile/ldap_users.py` remains unchanged (rollback safety)

**Caching:**

- LDAP user checks cached in Redis with TTL (default: 6 hours)
- Cache key: `ldap:<prefix>:users:check:<hash>`
- Double-check locking pattern for thread-safe cache updates

**Other Constraints:**

- Infra repo creates a single MR for all deleted users (not per-user)
- YAML modification uses `ruamel.yaml` to preserve formatting and comments
- VCS tokens resolved from app-interface VCS instances (not hardcoded)

## Required Components

**Vault Secrets:**

- LDAP credentials: `app-sre/creds/app-sre-ldap-ipa` (contains `bind_dn` and `bind_password`)
- VCS tokens: resolved from app-interface VCS instances via GraphQL

**External APIs:**

- FreeIPA LDAP server (direct `ldap3` connection via qontract-api)
- GitLab API (via qontract-api VCS external endpoints)

**Cache Backend:**

- Redis/Valkey connection required (for LDAP user check caching)
- Cache key prefix: SHA256 hash of `server_url:base_dn`
- TTL: 300 seconds (configurable via `QAPI_LDAP__USERS_CACHE_TTL`)

**Feature Toggles:**

- `ldap-users-api-allow-auto-merge-mrs`: Enable auto-merge on created MRs (default: `false`)

## Configuration

**App-Interface Schema:**

LDAP settings in `app-interface-settings-1.yml`:

```yaml
ldap:
  serverUrl: "ldap://freeipa.example.com"
  baseDn: "dc=example,dc=com"
  credentials:
    path: "app-sre/creds/app-sre-ldap-ipa"
    field: "all"
```

**Integration Settings:**

| Setting        | Environment Variable         | Default | Description                          |
| -------------- | ---------------------------- | ------- | ------------------------------------ |
| LDAP users TTL | `QAPI_LDAP__USERS_CACHE_TTL` | `21600` | LDAP user check cache TTL in seconds |

## Client Integration

**File:** `reconcile/ldap_users_api/integration.py`

**CLI Command:** `qontract-reconcile ldap-users-api`

**Arguments and Options:**

| Option                     | Required | Default                                                                               | Description                           |
| -------------------------- | -------- | ------------------------------------------------------------------------------------- | ------------------------------------- |
| `--app-interface-repo-url` | Yes      | —                                                                                     | App-interface GitLab repository URL   |
| `--infra-repo-url`         | Yes      | —                                                                                     | Infra GitLab repository URL           |
| `--infra-path`             | No       | `ansible/hosts/host_vars/bastion.ci.int.devshift.net`, `ansible/hosts/group_vars/all` | Infra YAML files to scan (repeatable) |
| `--label`                  | No       | `ldap-users`                                                                          | Labels to apply to MRs (repeatable)   |

**Example:**

```bash
qontract-reconcile ldap-users-api \
  --app-interface-repo-url https://gitlab.cee.redhat.com/service/app-interface \
  --infra-repo-url https://gitlab.cee.redhat.com/app-sre/infra \
  --label ldap-users \
  --label auto-cleanup
```

**Client Architecture:**

1. Fetches all users with resource paths from App-Interface (GraphQL)
2. Fetches LDAP settings (server URL, base DN, credentials) from App-Interface
3. Fetches VCS instances for token resolution
4. Calls `POST /external/ldap/users/check` to verify which users exist
5. Computes diff: users in app-interface but not in LDAP
6. Safety check: abort if LDAP returns empty
7. Dry-run: logs planned deletions and exits
8. Non-dry-run: resolves auto-merge from Unleash toggle, creates MRs via VCS endpoints

## Troubleshooting

**Issue: LDAP returns empty result set**

- **Symptom:** `RuntimeError: LDAP returned empty result set - aborting to prevent mass deletion`
- **Cause:** LDAP server unreachable, wrong credentials, or incorrect base DN
- **Solution:** Verify LDAP credentials in Vault, check server URL and base DN in app-interface settings

**Issue: MR already exists**

- **Symptom:** Log message `MR already exists for <username>: <url>`
- **Cause:** A deletion MR is already open for this user
- **Solution:** Review and merge/close the existing MR. The integration will skip users with open MRs.

**Issue: File not found (404) during YAML modification**

- **Symptom:** GABI/AWS/Schedule file operation skipped silently
- **Cause:** The referenced file path in app-interface no longer exists in the repository
- **Solution:** This is expected behavior — if the file doesn't exist, there's nothing to modify.

## References

**Code:**

- Client: [reconcile/ldap_users_api/](../../reconcile/ldap_users_api/)
- LDAP API (Layer 1): [qontract_utils/qontract_utils/ldap_api/](../../qontract_utils/qontract_utils/ldap_api/)
- LDAP external endpoints: [qontract_api/qontract_api/external/ldap/](../../qontract_api/qontract_api/external/ldap/)
- VCS external endpoints: [qontract_api/qontract_api/external/vcs/](../../qontract_api/qontract_api/external/vcs/)
- Design spec: [docs/superpowers/specs/2026-04-21-ldap-users-migration-design.md](../superpowers/specs/2026-04-21-ldap-users-migration-design.md)

**ADRs:**

- [ADR-008](../adr/ADR-008-qontract-api-client-integration-pattern.md) — QontractReconcileApiIntegration pattern
- [ADR-012](../adr/ADR-012-typed-models-over-dicts.md) — Typed Pydantic models
- [ADR-013](../adr/ADR-013-centralize-external-api-calls.md) — Centralize external API calls
- [ADR-014](../adr/ADR-014-three-layer-architecture-for-external-apis.md) — Three-layer architecture

**External:**

- [FreeIPA Documentation](https://freeipa.org/page/Documentation)
- [python-ldap3](https://ldap3.readthedocs.io/)
