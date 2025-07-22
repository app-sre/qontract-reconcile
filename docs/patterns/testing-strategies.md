# Testing Strategies

`qontract-reconcile` relies on a comprehensive suite of tests to ensure stability and prevent regressions. The project uses `pytest` as its testing framework and emphasizes unit testing for all new features and bug fixes.

Understanding the testing patterns is essential for contributing to the project.

## Core Principles

- **Unit Tests First**: The primary focus is on unit tests that are fast, isolated, and deterministic.
- **Mocking External Dependencies**: All external services and APIs must be mocked. Tests should never make live network calls.
- **Testing the Reconciliation Logic**: The most important thing to test is the core reconciliation logic: given a desired state and a current state, does the integration produce the correct "diff" and attempt to perform the right actions?

## Common Testing Patterns

**1. Mocking the GraphQL API (`gql`)**

Nearly every integration begins by fetching data from the `qontract-server` GraphQL API. In tests, this API is mocked to return controlled, predictable data.

A common pattern is to use the `mocker` fixture from `pytest-mock` to patch `gql.get_api()`. For integrations using the [`qenerate` pattern](./gql-data-binding.md), this is even simpler.

*Example: Mocking a `qenerate` query*
```python
from reconcile.gql_definitions.my_integration import my_query

def test_my_integration(mocker):
    # 1. Create mock data that matches the Pydantic models
    mock_data = my_query.MyQueryData(
        my_resources=[...]
    )

    # 2. Patch the generated query function
    mock_query = mocker.patch.object(my_query, 'query', return_value=mock_data)

    # 3. Run the integration's data fetching logic
    # This will now receive the mock_data instead of calling the real API
    resources = get_my_resources(query_func=mock_query)

    # 4. Assert that the logic behaves as expected
    assert len(resources) == len(mock_data.my_resources)
```

**2. Mocking External Service APIs**

When an integration interacts with an external API (like AWS, GitHub, or Quay), the client for that API must be mocked. This allows tests to verify that the integration is calling the correct API methods with the correct parameters.

*Example: Verifying an API call*
```python
def test_user_reconciliation(mocker):
    # Mock the GitHub API client
    mock_github_client = mocker.patch('reconcile.my_integration.github.get_client')
    mock_add_user = mock_github_client.return_value.add_user

    # Define desired state (e.g., a new user) and current state (empty)
    desired_users = [{'name': 'new-user'}]
    current_users = []

    # Run the reconciliation logic
    reconcile_users(desired_users, current_users, dry_run=False)

    # Assert that the 'add_user' method was called with the correct arguments
    mock_add_user.assert_called_once_with('new-user')
```

**3. Testing the `dry-run` Behavior**

Every integration must respect the `--dry-run` flag. Tests should cover both `dry_run=True` and `dry_run=False` scenarios to ensure that no modifying actions are taken when a dry run is requested.

```python
def test_user_reconciliation_dry_run(mocker):
    mock_github_client = mocker.patch('reconcile.my_integration.github.get_client')
    mock_add_user = mock_github_client.return_value.add_user

    # ... define desired and current state ...

    # Run with dry_run=True
    reconcile_users(desired_users, current_users, dry_run=True)

    # Assert that NO call was made to the API
    mock_add_user.assert_not_called()
```

By following these patterns, developers can create robust tests that verify the core logic of their integrations in isolation, leading to a more stable and reliable system.
