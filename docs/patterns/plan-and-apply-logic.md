# Declarative "Plan and Apply" Logic

A key safety feature of `qontract-reconcile` is its reliable `--dry-run` mode. To make this possible, well-structured integrations follow a declarative "plan and apply" pattern. This ensures that the logic for printing proposed changes is the exact same as the logic for executing them.

This pattern separates the *calculation* of changes from the *execution* of those changes.

## The "Plan and Apply" Workflow

Instead of performing actions as they are discovered, the integration first builds a comprehensive "plan" of all the changes it needs to make. This plan is the "diff" calculated during the core reconciliation loop.

**1. Build the Plan**

The integration compares the desired state with the current state and produces a structured plan of all the actions required. This plan is typically a data structure (like a list of objects) that represents the creations, updates, and deletions.

*Example: A plan for managing user roles*
```python
# This is a simplified example
class Action:
    def __init__(self, action, user, role):
        self.action = action
        self.user = user
        self.role = role

# ... inside the reconciliation logic ...
plan = []
if user_should_be_added:
    plan.append(Action("add_user", "new-user", "developer"))
if user_should_be_removed:
    plan.append(Action("remove_user", "old-user", None))
```

**2. Process the Plan**

After the entire plan has been built, the integration iterates over it and processes each action. The `--dry-run` flag is checked at this stage, right before the action is executed.

- **In dry-run mode (`--dry-run`)**: The integration prints a descriptive message for each action in the plan.
- **In "wet" mode**: The integration makes the actual API calls to execute the action.

*Example: Processing the plan*
```python
# The plan is now complete
for item in plan:
    if item.action == "add_user":
        logging.info(f"Adding user '{item.user}' with role '{item.role}'")
        if not dry_run:
            github_api.add_user_to_team(item.user, item.role)

    elif item.action == "remove_user":
        logging.info(f"Removing user '{item.user}'")
        if not dry_run:
            github_api.remove_user_from_org(item.user)
```

## Benefits of This Pattern

- **Safety and Reliability**: It guarantees that what you see in a dry run is exactly what will happen in a wet run. There is no possibility for the logic to diverge.
- **Auditability**: The dry-run output provides a clear and complete log of all intended changes, which can be reviewed and approved before execution.
- **Predictability**: The integration's behavior is easy to understand and reason about, as the "what" (the plan) is separated from the "how" (the execution).

This pattern is a cornerstone of Infrastructure as Code (IaC) and is critical for building trust in an automation tool that modifies live production systems.
