---
description: Document an existing qontract-api integration
scope: project
---

# Document qontract-api Integration

You are helping document an existing qontract-api integration for the qontract-reconcile developer documentation.

## Purpose

This command analyzes an existing qontract-api integration and generates comprehensive documentation that will be added to `docs/integrations/`. The goal is to help new developers understand:

- What the integration does
- How it works (architecture)
- What features it provides
- What limitations it has
- What components are required
- How to use it

## Template

Use the template from `docs/integrations/template.md` as the structure for all integration documentation.

## Workflow

1. **Ask for integration name**
   - Prompt user for the integration name (e.g., "slack-usergroups")
   - Validate that the integration exists in `qontract_api/qontract_api/integrations/<name>/`

2. **Read the template**
   - Read `docs/integrations/template.md` to understand the structure
   - Use this template as the basis for the documentation

3. **Analyze the integration** by reading:
   - **Server-side code:**
     - `qontract_api/qontract_api/integrations/<name>/models.py` - Request/Response/Action models
     - `qontract_api/qontract_api/integrations/<name>/service.py` - Business logic
     - `qontract_api/qontract_api/integrations/<name>/router.py` - API endpoints
     - Other files in the integration directory (factory, client, etc.)
   - **Client-side code:**
     - `reconcile/<name>_api.py` - Client integration
   - **Related ADRs:**
     - Check which ADRs are referenced in docstrings/comments
     - Read relevant ADRs for architectural context

4. **Extract information:**

   Extract all information needed to fill the template sections:

   **Features:**
   - What does the integration do? (from docstrings, service logic)
   - What actions can it perform? (from action models)
   - What resources does it manage? (from models)

   **API Endpoints:**
   - List all endpoints (POST, GET) with paths
   - Document parameters and responses

   **Request/Response Models:**
   - Document the Pydantic model structure
   - Include key fields with descriptions
   - Note validation rules (e.g., dry_run default=True)

   **Actions:**
   - List all action types (from discriminated union models)
   - Describe what each action does

   **Architecture:**
   - Client-side responsibilities (GraphQL, desired state)
   - Server-side responsibilities (current state, diff, actions)
   - External API dependencies

   **Limits/Constraints:**
   - Dry-run default (safety)
   - Managed resources (e.g., managed_usergroups whitelist)
   - Rate limits
   - Cache TTLs
   - Any other constraints

   **Required Components:**
   - Vault token paths
   - External API credentials
   - Environment variables
   - Cache backend

5. **Generate documentation following the template:**
   - Use `docs/integrations/template.md` as the exact structure
   - Fill in all sections with information extracted from the code
   - Keep the template structure intact - do not skip sections
   - If a section is not applicable, note "[Not applicable for this integration]"
   - Follow the exact markdown formatting from the template

6. **Create integration documentation file:**
   - Create directory if needed: `docs/integrations/`
   - Create file: `docs/integrations/<name>.md`
   - Use the filled template
   - Include all sections from the template

7. **Update README.md:**
   - Read and update `docs/integrations/README.md` accordingly
   - Look for "## Integrations" section
     - If exists: Add link to the new integration documentation
     - If not exists: Create section after "## Documentation" section with:

       ```markdown
       ## Integrations

       Available integrations:

       - [Integration Name](docs/integrations/<name>.md) - Brief description
       ```

   - Add link in alphabetical order
   - Keep existing content intact

8. **Output:**
   - Show a summary of the generated documentation to the user
   - Ask for confirmation before writing files
   - Write `docs/integrations/<name>.md`
   - Update `docs/integrations/README.md` with link to the new documentation

## Important Guidelines

- **Follow the template**: Use the exact structure from `docs/integrations/template.md`
- **Be comprehensive**: Include all important details a new developer needs
- **Be accurate**: Extract information from actual code, not assumptions
- **Be clear**: Use simple language, avoid jargon where possible
- **Be consistent**: Follow the template formatting exactly
- **Complete all sections**: Fill in every section from the template, or mark as "[Not applicable]"
- **Reference ADRs**: Link to relevant architectural decisions
- **Include examples**: Show practical usage with curl commands and CLI
- **Highlight safety**: Emphasize dry_run defaults and safety features
- **Update metadata**: Set Last Updated date and Maintainer information

## Example Interaction

User: `/document-api-integration`
Assistant: I'll help you document a qontract-api integration. Which integration would you like to document?

User: slack-usergroups
Assistant:
[Reads template from docs/integrations/template.md]
[Reads integration files from qontract_api/qontract_api/integrations/slack-usergroups/]
[Reads client integration from reconcile/slack_usergroups_api.py]
[Analyzes code and extracts all required information]
[Fills template with extracted information]

I've analyzed the slack-usergroups integration and generated comprehensive documentation following the standard template.

**Documentation Summary:**

- API Path: /api/v1/integrations/slack-usergroups
- Features: 5 features (usergroup management, user sync, channel sync, etc.)
- Actions: 3 action types (create, update_users, update_metadata)
- External API: Slack API
- Required: Vault tokens, Redis cache

**Files to create/update:**

1. `docs/integrations/slack-usergroups.md` (new file with full template)
2. `docs/integrations/README.md` (add link in Integrations section)

Should I create these files?

User: yes
Assistant:
[Creates directory docs/integrations/ if needed]
[Creates docs/integrations/slack-usergroups.md with filled template]
[Updates docs/integrations/README.md with link in Integrations section]

Documentation created successfully!

**Created:**

- `docs/integrations/slack-usergroups.md` (comprehensive integration documentation)

**Updated:**

- `docs/integrations/README.md` (added link: `- [Slack Usergroups](docs/integrations/slack-usergroups.md) - Manage Slack usergroups via API`)

The integration is now fully documented with all sections from the template.
