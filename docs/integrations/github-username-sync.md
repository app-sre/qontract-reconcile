# github-username-sync

**Last Updated:** 2026-10-29

## Description

Keeps the `github_username` field on internal App-Interface users in sync with the GitHub account they've linked in their Rover profile. LDAP's `rhatSocialURL` attribute is the source of truth for the link, but it is untrusted data: it may name a GitHub account that no longer exists, point at a GitHub organization instead of a personal account, or only ever carry a lowercased login. The integration therefore cross-checks every LDAP-linked login against the GitHub API before proposing a correction, and proposes a single batched app-interface MR for all drifted users in a run.

## Features

- Resolves each internal user's Rover-linked GitHub account via LDAP's `rhatSocialURL`, through qontract-api's external LDAP endpoint (cached, FreeIPA-authenticated)
- Validates every LDAP-linked login against the GitHub API via qontract-api's external GitHub endpoint — filters out logins that don't exist and logins that resolve to an organization rather than a personal account
- Corrects case-only mismatches using GitHub's own canonical casing (LDAP only ever yields a lowercased login)
- Users with no unambiguous LDAP-linked GitHub account, or whose linked login fails GitHub validation, are reported via a warning log and left untouched — never guessed
- Creates a single batched MR per run (not one per user) via the VCS file-sync endpoint
- Auto-merge gated behind an Unleash toggle, and additionally suppressed above a configurable `--auto-merge-threshold` (adds the review-queue label)
- Dry-run runs LDAP resolution and GitHub validation (needed to compute and log accurate proposed updates), then exits before any VCS file lookup or MR creation

## Desired State Details

Internal users are queried from `users_v1` in App-Interface:

- `path` — the user's YAML file path (schema-relative; normalized to the repo-root-relative form before VCS reads/writes)
- `org_username` — the LDAP uid, used to join against the LDAP-resolved GitHub mapping
- `github_username` — the value currently stored in app-interface, compared against the validated GitHub login

LDAP settings (server URLs, base DN, credentials) are configured in `app-interface-settings-1.yml` under `ldap`. The GitHub API token used for validation is taken from the `githuborg_v1` entry flagged `default: true`.

## Architecture

**Architecture Pattern:** Client-side diff/business logic + two independent external lookups (LDAP, GitHub) + server-side VCS file-sync reconciliation

```text
reconcile/github_username_sync/          (client - diff + MR building)
    │
    ├── GraphQL ──────────────────────→ app-interface (users: path, org_username, github_username)
    ├── GraphQL ──────────────────────→ app-interface (LDAP settings, default GitHub org token)
    │
    ├── POST /external/ldap/org-github-usernames ──→ qontract_api (org_username -> lowercased GitHub login)
    │
    ├── POST /external/github/users/validate ───────→ qontract_api (filter to existing personal accounts,
    │                                                    canonical casing)
    │
    ├── join + diff locally ──────────→ (which org_usernames have a genuinely different, validated login?)
    │
    ├── GET /external/vcs/repos/file ──→ read each user's YAML file
    │
    └── POST /external/vcs/file-sync ──→ reconcile file state (dedup + create MR)
```

**Client-Side (`reconcile/github_username_sync/integration.py`):**

- Fetches users (path, org_username, github_username) from App-Interface (GraphQL)
- Fetches LDAP settings and the default GitHub org's token from App-Interface (GraphQL)
- Resolves `org_username -> lowercased GitHub login` via `/external/ldap/org-github-usernames`
- Validates the distinct set of LDAP-linked logins via `/external/github/users/validate` (`account_type=User`) — only `org_username`/GitHub login pairs are built locally; `org_username` is never sent to the GitHub endpoint
- Builds `org_username -> canonical GitHub login` by joining the LDAP mapping with the GitHub validation result, dropping any login that failed validation
- Computes drift with an exact string comparison (no case-insensitive fallback — the mapping already carries GitHub's canonical casing)
- Logs proposed updates; dry-run stops here
- Non-dry-run: resolves the VCS secret for the app-interface repo, resolves auto-merge from the Unleash toggle (forced off above the threshold), and reconciles via a single batched VCS file-sync request

**Server-Side (external endpoints):**

- `POST /external/ldap/org-github-usernames` — resolves every LDAP uid's linked GitHub account (ambiguous links, from a shared login or a uid with multiple links, are omitted)
- `POST /external/github/users/validate` — looks up each GitHub username via the GitHub API (cached, including negative caching of 404s), optionally filtered by `account_type`
- `GET /external/vcs/repos/file` — read file content for YAML modification
- `POST /external/vcs/file-sync` — reconcile file state (read current, validate, dedup by title, create MR)

## API Endpoints

This integration uses shared external endpoints.

### Resolve LDAP-linked GitHub usernames

```http
POST /api/v1/external/ldap/org-github-usernames
Authorization: Bearer <JWT_TOKEN>
Content-Type: application/json
```

**Request Body:**

```json
{
  "secret": {
    "secret_manager_url": "https://vault.example.com",
    "path": "secret/data/path/to/ldap-credentials",
    "server_urls": ["ldap://freeipa.example.com", "ldap://replica.example.com"],
    "base_dn": "dc=example,dc=com"
  }
}
```

**Response:**

```json
{
  "users": [
    {"org_username": "cluo", "github_username": "chunxialexluo"}
  ]
}
```

Logins are always lowercased — this is the LDAP data source's limitation that GitHub validation exists to correct.

### Validate GitHub usernames

```http
POST /api/v1/external/github/users/validate
Authorization: Bearer <JWT_TOKEN>
Content-Type: application/json
```

**Request Body:**

```json
{
  "secret": {
    "secret_manager_url": "https://vault.example.com",
    "path": "secret/data/path/to/github-token",
    "field": "token"
  },
  "usernames": ["chunxialexluo", "mnovak1"],
  "account_type": "User"
}
```

**Response:**

```json
{
  "users": [
    {"login": "ChunxiAlexLuo", "type": "User"}
  ]
}
```

`mnovak1` is omitted because it does not exist on GitHub (a 404 from the GitHub API). `account_type` is optional — when set, accounts of another type (e.g. an organization) are treated the same as not found; when omitted, both users and organizations are returned. This endpoint carries no knowledge of app-interface or LDAP — it is a generic GitHub username validator, reusable by any future integration that needs one.

### File Sync Reconciliation

Same `POST /api/v1/external/vcs/file-sync` endpoint used by `ldap-users-api` — see [ldap-users.md](ldap-users.md#file-sync-reconciliation) for the full request/response shape. All drifted users in a run are batched into a single request with a fixed title, so at most one `github_username` sync MR is open at a time.

### Models

**`compute_updates` comparison:**

| Stored `github_username` | Validated GitHub login | Outcome |
| ------------------------- | ----------------------- | ------- |
| `alice-old`                | `alice-new`              | Updated |
| `bob123`                   | `Bob123`                 | Updated (case-only correction) |
| `carol-gh`                 | `carol-gh`               | No change |
| any                        | *(no validated mapping)* | No change — reported via warning log |

## Limits and Constraints

**Safety:**

- No guessing: a user with no unambiguous LDAP-linked GitHub account, or whose linked login fails GitHub validation (non-existent or an organization), is left untouched and named in a warning log
- `auto_merge` defaults to `false` — controlled via Unleash feature toggle `github-username-sync-allow-auto-merge-mrs`
- `auto_merge` is additionally forced to `false`, regardless of the Unleash toggle, when the number of updates in a run exceeds `--auto-merge-threshold` (default `10`); the `show-self-serviceable-in-review-queue` label is added so the MR shows up in the IC review queue
- MR deduplication: file-sync endpoint checks for existing open MRs by title before creating new ones

**Caching (GitHub validation):**

- Positive lookups (account found): cached per-username, TTL `user_cache_ttl` (default 12 hours)
- Negative lookups (404, i.e. account doesn't exist): cached per-username with a shorter TTL, `user_not_found_cache_ttl` (default 5 minutes), so a newly-created account isn't treated as non-existent for too long
- Rate-limit marker: on a GitHub rate-limit response, a marker is cached (TTL derived from GitHub's reset time, capped at `user_cache_ttl`) so the remainder of the batch short-circuits instead of repeating doomed calls

**Other Constraints:**

- Comparison between stored and validated `github_username` is exact (case-sensitive) — this is what allows case-only corrections, unlike the previous LDAP-only comparison which had to skip them
- VCS tokens resolved from app-interface VCS instances (not hardcoded)
- YAML modification uses `ruamel.yaml` to preserve formatting and comments

## Required Components

**Vault Secrets:**

- LDAP credentials: resolved from `app-interface-settings-1.yml` (`ldap.credentials`)
- GitHub API token: resolved from the `githuborg_v1` entry flagged `default: true`
- VCS tokens: resolved from app-interface VCS instances via GraphQL

**External APIs:**

- FreeIPA LDAP server (direct `ldap3` connection via qontract-api)
- GitHub REST API (`GET /users/{username}`, via qontract-api)
- GitLab API (via qontract-api VCS external endpoints)

**Cache Backend:**

- Redis/Valkey connection required (for GitHub user lookup and LDAP mapping caching)

**Feature Toggles:**

- `github-username-sync-allow-auto-merge-mrs`: Enable auto-merge on created MRs (default: `false`)

## Configuration

**Integration Settings:**

| Setting                          | Environment Variable                       | Default | Description                                   |
| --------------------------------- | ------------------------------------------- | ------- | ---------------------------------------------- |
| GitHub user lookup cache TTL       | `QAPI_GITHUB_ORG__USER_CACHE_TTL`           | `43200` | GitHub user lookup (found) cache TTL in seconds (12 hours) |
| GitHub user not-found cache TTL    | `QAPI_GITHUB_ORG__USER_NOT_FOUND_CACHE_TTL` | `300`   | GitHub user lookup (404) cache TTL in seconds (5 minutes) |

## Client Integration

**File:** `reconcile/github_username_sync/integration.py`

**CLI Command:** `qontract-reconcile github-username-sync`

**Arguments and Options:**

| Option                     | Required | Default               | Description                                                                                  |
| -------------------------- | -------- | ---------------------- | ---------------------------------------------------------------------------------------------- |
| `--app-interface-repo-url` | Yes      | —                      | App-interface GitLab repository URL                                                           |
| `--app-interface-target-branch` | No  | `master`               | App-interface repository target branch                                                        |
| `--label`                  | No       | `github-username-sync` | Labels to apply to the created MR (repeatable)                                                 |
| `--auto-merge-threshold`   | No       | `10`                   | Suppress auto-merge and add the review-queue label when a run's update count exceeds this     |

**Example:**

```bash
qontract-reconcile github-username-sync \
  --app-interface-repo-url https://gitlab.cee.redhat.com/service/app-interface \
  --label github-username-sync
```

**Client Architecture:**

1. Fetches users (path, org_username, github_username) from App-Interface
2. Fetches LDAP settings and resolves the default GitHub org's token
3. Calls `POST /external/ldap/org-github-usernames` to get the LDAP-linked login per `org_username`
4. Warns about `org_username`s with no unambiguous LDAP-linked account
5. Calls `POST /external/github/users/validate` with the distinct set of linked logins, `account_type=User`
6. Warns about linked logins that failed GitHub validation (non-existent or an organization)
7. Diffs the validated mapping against each user's stored `github_username` (exact comparison)
8. Dry-run: logs proposed updates and exits
9. Non-dry-run: resolves auto-merge from the Unleash toggle, forces it off (and adds the review-queue label) above `--auto-merge-threshold`, then reconciles via a single batched VCS file-sync request

## Troubleshooting

**Issue: User reported as having "no unambiguous LDAP-linked GitHub account"**

- **Symptom:** Warning log naming one or more `org_username`s
- **Cause:** The user has no `rhatSocialURL` pointing at GitHub, or has multiple such entries (either their own, or sharing a login with another LDAP uid)
- **Solution:** The user should update their Rover profile to link exactly one GitHub account. No action needed on the app-interface side — nothing is changed for these users.

**Issue: Linked login reported as "does not exist or is not a personal account"**

- **Symptom:** Warning log naming one or more GitHub logins (not `org_username`s — the same login can affect multiple users only in pathological LDAP data)
- **Cause:** The GitHub account linked in Rover was deleted/renamed away, never existed, or is a GitHub organization rather than a personal account
- **Solution:** The user should re-link the correct personal GitHub account in Rover. The stored `github_username` is left untouched until then.

**Issue: MR already exists**

- **Symptom:** Log message `MR already exists: <url>`
- **Cause:** A batched sync MR from a previous run is still open (MR deduplication is by fixed title)
- **Solution:** Review and merge/close the existing MR. New drift discovered while it's open is recomputed and picked up in the next MR once the current one merges.

## References

**Code:**

- Client: [reconcile/github_username_sync/](../../reconcile/github_username_sync/)
- GitHub API (Layer 1): [qontract_utils/qontract_utils/github_api/](../../qontract_utils/qontract_utils/github_api/)
- GitHub external endpoints: [qontract_api/qontract_api/external/github/](../../qontract_api/qontract_api/external/github/)
- LDAP external endpoints: [qontract_api/qontract_api/external/ldap/](../../qontract_api/qontract_api/external/ldap/)
- VCS external endpoints: [qontract_api/qontract_api/external/vcs/](../../qontract_api/qontract_api/external/vcs/)

**ADRs:**

- [ADR-008](../adr/ADR-008-qontract-api-client-integration-pattern.md) — QontractReconcileApiIntegration pattern
- [ADR-012](../adr/ADR-012-typed-models-over-dicts.md) — Typed Pydantic models
- [ADR-013](../adr/ADR-013-centralize-external-api-calls.md) — Centralize external API calls
- [ADR-014](../adr/ADR-014-three-layer-architecture-for-external-apis.md) — Three-layer architecture

**External:**

- [GitHub REST API — Users](https://docs.github.com/en/rest/users/users)
