# Qontract-Reconcile Integrations

This directory contains documentation for qontract-reconcile integrations.
Most entries follow the qontract-api client/server pattern; CLI-only
integrations (not yet migrated) use the same section template and note
where HTTP endpoints do not apply.

## Architecture

qontract-api integrations follow a split architecture:

- **Client-Side** (`reconcile/<name>_api.py`): Fetches desired state from App-Interface GraphQL API
- **Server-Side** (`qontract_api/integrations/<name>/`): Fetches current state and performs reconciliation

CLI integrations implement plan-and-apply entirely under `reconcile/` and
document that layout under **Architecture** / **Client Integration** instead
of API endpoints.

## Integrations

Available integrations:

- [GitHub Owners](github-owners.md) - Manage GitHub organization admin (owner) membership based on App-Interface roles with add-only safety semantics
- [Glitchtip](glitchtip.md) - Manage Glitchtip organizations, teams, projects, and users across instances with LDAP group enrichment
- [Glitchtip Project Alerts](glitchtip-project-alerts.md) - Manage Glitchtip project alert configurations across instances with email/webhook recipients and Jira integration
- [LDAP Users](ldap-users.md) - Remove orphaned users from app-interface and infra repos when no longer in LDAP (client-orchestrated pattern)
- [OCM OIDC Identity Provider](ocm-oidc-idp.md) - Reconcile OCM OIDC identity providers for RHIDP-enabled clusters against the SSO client secrets sso-client-api writes to Vault
- [OpenShift Namespaces](openshift-namespaces.md) - Reconcile Kubernetes/OpenShift namespaces across clusters with cached existence checks and idempotent create/delete
- [Quay Robot Accounts](quay-robot-accounts.md) - Manage Quay organization robot accounts (CLI integration; org opt-in via `managedRobotAccounts`)
- [RHIDP SSO Client](rhidp-sso-client.md) - Manage Keycloak SSO clients for RHIDP-enabled OCM clusters, discovered via OCM labels and qontract-api's external OCM endpoint
- [Slack Usergroups](slack-usergroups.md) - Manage Slack usergroups across workspaces with automatic membership from roles, schedules, git ownership, and PagerDuty

## Documentation Template

New integrations should follow the standard template: [integration-template.md](../integration-template.md)

Use the `/document-api-integration` slash command to generate documentation for existing integrations.
