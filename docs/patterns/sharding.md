# Sharding

Sharding is a horizontal scaling technique used to divide the workload of a single integration into smaller, independent chunks called shards. This is crucial for integrations that manage a large number of resources (e.g., hundreds of clusters or thousands of AWS accounts), as it allows the work to be parallelized.

## Standard Sharding (via `integrations-manager`)

The standard and most common way to configure sharding is declaratively in `app-interface`. The `integrations-manager` reads this configuration and creates the necessary Kubernetes resources (e.g., one `Deployment` per shard).

### Sharding Strategies

Sharding is configured on a per-integration basis using one of several strategies:

*   **`static`**: The workload is divided into a fixed number of shards.
*   **`per-openshift-cluster`**: A dedicated shard is created for each OpenShift cluster.
*   **`per-aws-account`**: A dedicated shard is created for each AWS account.
*   ... and others.

### Configuration

Sharding is configured in `app-interface` within the `managed` block of an integration's definition file.

**Example: Static Sharding**

This configuration will run the integration in a specific namespace with a static number of shards.

```yaml
# In /data/integrations/my-integration.yml
managed:
- namespace:
    $ref: /services/app-interface/namespaces/app-interface-stage.yml
  sharding:
    strategy: static
    shards: 2
```

**Example: Per-Cluster Sharding with Overrides**


This will create a separate deployment for each OpenShift cluster. It also demonstrates `shardSpecOverrides`, which allow you to customize the resources for specific shards (clusters).

```yaml
# In /data/integrations/my-integration.yml
managed:
- namespace:
    $ref: /services/app-interface/namespaces/app-interface-production.yml
  sharding:
    strategy: per-openshift-cluster
    shardSpecOverrides:
    - shard:
        $ref: /openshift/big-cluster.yml
      resources:
        requests:
          memory: 1Gi
          cpu: 200m
        limits:
          memory: 2Gi
```
This configuration is explained in more detail in the [Integration Deployment Model](./integration-deployment-model.md).

## Affected-Shard Optimization (for PR Checks)

For PR checks, running all shards can be inefficient if a change only affects one resource. `qontract-reconcile` has an advanced optimization to run *only the shards affected by a PR*.

This pattern is enabled by implementing the `get_desired_state_shard_config()` method in an integration.

### How It Works

1.  **Define Shard Configuration**: The integration's `get_desired_state_shard_config()` method returns a `DesiredStateShardConfig` object. This object tells the runtime how to map an item in the desired state to a unique shard key (e.g., a cluster name).

2.  **Calculate Desired State Diff**: When the integration is run with an `--early-exit-compare-sha` (as it is in a PR check), the runtime calculates a diff of the desired state between the two commits.

3.  **Identify Affected Shards**: The runtime uses the `DesiredStateShardConfig` to process this diff and identify which specific shard keys are affected by the changes.

4.  **Execute Only Affected Shards**: The integration is then executed, but it will only process the items belonging to the affected shards.

### Example Implementation

```python
# In my_integration.py
from reconcile.utils.runtime.integration import (
    DesiredStateShardConfig,
    QontractReconcileIntegration,
)

class MyIntegration(QontractReconcileIntegration):
    def get_desired_state_shard_config(self) -> DesiredStateShardConfig:
        return DesiredStateShardConfig(
            # The CLI argument to pass to the sharded run, e.g., --cluster-name
            shard_arg_name="cluster-name",
            # A JSON path selector to extract the list of items to be sharded
            shard_path_selectors=["clusters[*]"],
            # A JSON path selector to extract the shard key from each item
            shard_key_selector="name",
        )
```

## Legacy Sharding (`is_in_shard`)

Some older integrations use a manual, hash-based sharding method directly in their Python code using the `reconcile.utils.sharding.is_in_shard(key)` utility function. This pattern is being actively phased out and should not be used for new integrations.
