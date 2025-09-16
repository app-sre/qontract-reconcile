# Caching and Early Exit

`early_exit` and `extended_early_exit` are frameworks designed to prevent redundant integration runs, saving execution time and reducing load on external APIs. Both work by determining if an integration's "desired state" has changed since a previous run.

## Core Concept: Desired State Function

To be eligible for early exit, an integration must implement a function that returns its desired state as a dictionary. By convention, this function is named `get_early_exit_desired_state()` or `early_exit_desired_state()`.

```python
# in my_integration.py

def get_early_exit_desired_state(*args, **kwargs) -> dict[str, Any]:
    """
    Fetches and returns a dictionary representing the desired state
    for this integration. This dictionary will be serialized to JSON
    and hashed to check for changes.
    """
    # This should be the same data used in the integration's run method.
    data = fetch_data_from_qontract_server()
    return data
```

This function's output is used as the basis for comparison in both early exit mechanisms.

## Standard `early_exit` (Git-Based)

The standard `early_exit` mechanism is designed for integrations whose desired state is defined entirely by data within the `app-interface` git repository. It works by comparing the desired state between the current commit and a previously specified commit.

**How it Works:**

1.  The user provides a git commit SHA via the `--early-exit-compare-sha <sha>` CLI argument.
2.  `qontract-reconcile` runs the `get_early_exit_desired_state()` function against both the current `HEAD` and the specified compare SHA.
3.  If the JSON representation of the two desired states is identical, the integration exits immediately with a success code.

**Use Cases:**

-   Ideal for CI/CD pipelines where you only want to run integrations if their relevant configuration has changed between two commits.

## `extended_early_exit` (Cache-Based)

The `extended_early_exit` mechanism provides a more flexible, time-based caching solution. It is not tied to git history, making it suitable for integrations that run on a schedule.

**How it Works:**

`extended_early_exit` uses a remote cache (e.g., in an S3 bucket) to store the results of successful integration runs.

1.  The user enables the feature with the `--enable-extended-early-exit` flag and can specify a cache duration with `--extended-early-exit-cache-ttl-seconds <seconds>`.
2.  The framework calculates a unique cache key based on a hash of the desired state, the integration name, and other parameters.
3.  It checks the cache:
    -   **CACHE HIT:** A valid, non-expired entry exists. The framework raises `SystemExit`, and the integration run is skipped.
    -   **CACHE MISS/EXPIRED:** No valid entry is found. The integration proceeds with its `run()` method.
4.  If the integration `run()` method completes successfully, its log output is captured and stored in the cache with the specified TTL.

**How to Implement:**

Integrations must be explicitly instrumented to use this feature by calling `extended_early_exit_run()` within their main `run` function.

```python
# in my_integration.py (example)
from reconcile.utils.extended_early_exit import extended_early_exit_run

# ... integration class definition ...

    def run(self, dry_run: bool) -> None:
        # This function is passed to the early exit runner
        def integration_run_function() -> None:
            # All the integration logic goes here
            # ...
            pass

        extended_early_exit_run(
            integration=self.name,
            dry_run=dry_run,
            cache_source=self.get_early_exit_desired_state(),
            ttl_seconds=self.params.extended_early_exit_cache_ttl_seconds,
            integration_run_function=integration_run_function,
        )
```

**Use Cases:**

-   Integrations running on a cron schedule that fetch data from external sources.
-   Reducing load on rate-limited APIs by avoiding unnecessary calls when the desired state hasn't changed.
