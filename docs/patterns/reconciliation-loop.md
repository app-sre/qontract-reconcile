# The Core Reconciliation Loop

The fundamental pattern at the heart of nearly every integration in `qontract-reconcile` is the **reconciliation loop**. The purpose of this loop is to ensure that the state of a managed resource in a live, external system matches the state defined in `app-interface`.

This is achieved by comparing the *desired state* with the *current state* and then taking action to resolve any differences.

## How It Works

The reconciliation loop consists of four main steps:

**1. Fetch Desired State**

The integration first gathers the configuration for its resources as defined in `app-interface`. This is the "source of truth." This is typically done using a `qenerate`-generated GraphQL query.

```python
# 1. Fetch desired state from app-interface
desired_users = get_users_from_app_interface()
# desired_users is a list of User objects with their required roles
```

**2. Fetch Current State**

Next, the integration connects to the external service's API (e.g., GitHub, AWS, Quay) to get the current, real-world state of the resources.

```python
# 2. Fetch current state from the live service
current_users = get_users_from_github_api()
# current_users is a list of users and their current roles from the GitHub API
```

**3. Calculate the Diff**

The integration then compares the desired state with the current state to produce a list of differences. This "diff" contains the actions required to make the current state match the desired state.

The actions usually fall into three categories:
- **Create**: A resource exists in the desired state but not in the current state.
- **Update**: A resource exists in both states, but its attributes are different.
- **Delete**: A resource exists in the current state but not in the desired state.

```python
# 3. Calculate the diff
diff = calculate_diff(desired_users, current_users)
# diff might look like:
# {
#   "create": [{"user": "new-user", "role": "member"}],
#   "update": [{"user": "existing-user", "role": "admin"}], # was "member"
#   "delete": [{"user": "old-user"}]
# }
```

**4. Act**

Finally, the integration acts on the calculated diff to apply the changes to the external service. All actions must respect the `--dry-run` flag. This is a critical safety feature, and it is typically implemented using the **[Declarative "Plan and Apply" Logic](./plan-and-apply-logic.md)**.

- In a **dry run**, the integration only prints the actions it *would* take.
- In a "wet" run, the integration executes the API calls to create, update, or delete the resources.

```python
# 4. Act on the diff
for user_to_add in diff["create"]:
    if dry_run:
        print(f"ADD: Add {user_to_add['user']} with role {user_to_add['role']}")
    else:
        github_api.add_user(user_to_add)

for user_to_delete in diff["delete"]:
    if dry_run:
        print(f"DELETE: Remove {user_to_delete['user']}")
    else:
        github_api.remove_user(user_to_delete)
```

This declarative `desired vs. current` model is the cornerstone of `qontract-reconcile`, providing idempotent and predictable management of cloud and SaaS resources.
