---
name: document-api-integration
description: Generate comprehensive documentation for a qontract-api integration. Use this skill when a new integration has been created or migrated to qontract-api and needs documentation, or when someone asks to document an integration. Triggers on requests mentioning integration documentation, documenting API integrations, or after completing a migration with /migrate-integration.
---

# Document qontract-api Integration

Analyze an existing qontract-api integration and generate documentation following the standard template at `docs/integrations/template.md`.

## Input

Integration name (e.g., "slack-usergroups"). If not provided, ask for it.

Validate the integration exists at `qontract_api/qontract_api/integrations/<name>/` before proceeding.

## Workflow

1. **Read the template** from `docs/integrations/template.md`

2. **Analyze the integration** by reading:
   - `qontract_api/qontract_api/integrations/<name>/models.py` - Request/Response/Action models
   - `qontract_api/qontract_api/integrations/<name>/service.py` - Business logic
   - `qontract_api/qontract_api/integrations/<name>/router.py` - API endpoints
   - `qontract_api/qontract_api/integrations/<name>/tasks.py` - Celery tasks
   - Other files in the integration directory (factory, client, etc.)
   - `reconcile/<name>_api.py` or `reconcile/<name>_api/` - Client integration
   - Related ADRs referenced in docstrings/comments

3. **Extract information** for each template section:
   - **Features**: What it does, actions it can perform, resources it manages
   - **API Endpoints**: POST/GET paths, parameters, responses
   - **Models**: Pydantic structure, key fields, validation rules (dry_run default=True)
   - **Actions**: All action types from discriminated union models
   - **Architecture**: Client-side vs server-side responsibilities
   - **Limits/Constraints**: Safety features, rate limits, cache TTLs, managed resources
   - **Required Components**: Vault secrets, external APIs, environment variables

4. **Generate documentation** using the template structure exactly. Fill all sections. Mark non-applicable sections as "[Not applicable for this integration]".

5. **Show summary** to user before writing:
   - API path, features count, action types, external APIs, requirements

6. **Write files** after confirmation:
   - Create `docs/integrations/<name>.md`
   - Update `docs/integrations/README.md` with link in alphabetical order

## Guidelines

- Follow the template structure from `docs/integrations/template.md` exactly
- Extract information from actual code, not assumptions
- Reference relevant ADRs
- Include practical usage examples (curl commands, CLI)
- Emphasize dry_run defaults and safety features
- Set Last Updated date to today
