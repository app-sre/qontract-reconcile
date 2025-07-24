# Observability: Logging and Metrics

To ensure that `qontract-reconcile` is running reliably, the project has standardized patterns for logging and exposing Prometheus metrics. Proper observability is crucial for monitoring the health of integrations and diagnosing issues when they arise.

## Structured Logging

The project uses the standard Python `logging` module, but with a convention of providing structured information where possible. Log messages should be clear, concise, and provide context that is useful for a human operator.

A key practice is to include key identifiers in log messages, such as the integration name, the cluster, or the resource being processed.

*Example: Good vs. Bad Logging*
```python
# Bad: Lacks context
logging.info("Deleting user")

# Good: Provides key identifiers
logging.info(f"[{self.integration}] Deleting user '{user_name}' from org '{org_name}'")
```

## Prometheus Metrics

`qontract-reconcile` uses a set of utility functions to expose Prometheus metrics. These metrics are typically sent to a Prometheus Pushgateway, allowing them to be scraped and monitored from a central location.

The primary metric types used are **Counters** and **Gauges**.

### Counters

Counters are used to track events that occur over time, such as the number of errors or the number of resources reconciled. The `reconcile.utils.metrics.inc_counter()` function is used for this.

*Example: Tracking errors in an integration*
```python
from reconcile.utils import metrics

try:
    # ... reconciliation logic ...
except Exception as e:
    # Increment a counter for every error
    metrics.inc_counter(
        name='my_integration_errors',
        integration=QONTRACT_INTEGRATION,
        labels={'details': str(e)}
    )
    raise
```

### Gauges

Gauges are used to represent a value that can go up or down, such as the number of items in a queue or the number of currently managed resources. The `reconcile.utils.metrics.set_gauge()` function is used for this.

*Example: Reporting the number of managed users*
```python
from reconcile.utils import metrics

# Get the list of users
users = get_all_users()
user_count = len(users)

# Set a gauge to the current number of users
metrics.set_gauge(
    name='my_integration_managed_users',
    integration=QONTRACT_INTEGRATION,
    value=user_count
)
```

### The `ResourceInventory` Metrics

For integrations that use the **[OpenShift Resource Management](./openshift-resource-management.md)** pattern, the `openshift_base.publish_metrics(ri, ...)` function automatically exposes a set of standard metrics based on the contents of the `ResourceInventory`.

These metrics include:
- `qontract_reconcile_desired_resources`
- `qontract_reconcile_current_resources`
- `qontract_reconcile_changed_resources`

This provides a consistent, high-level overview of the state of OpenShift-based integrations without requiring any custom metric instrumentation.
