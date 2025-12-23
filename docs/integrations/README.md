# Qontract-Reconcile Integrations

This directory contains documentation for qontract-api integrations - server-side reconciliation integrations that follow the client-server architecture pattern.

## Architecture

qontract-api integrations follow a split architecture:

- **Client-Side** (`reconcile/<name>_api.py`): Fetches desired state from App-Interface GraphQL API
- **Server-Side** (`qontract_api/integrations/<name>/`): Fetches current state and performs reconciliation

## Integrations

Available integrations:

- [Slack Usergroups](slack-usergroups.md) - Manage Slack usergroups across workspaces with automatic membership from roles, schedules, git ownership, and PagerDuty

## Documentation Template

New integrations should follow the standard template: [integration-template.md](../integration-template.md)

Use the `/document-api-integration` slash command to generate documentation for existing integrations.
