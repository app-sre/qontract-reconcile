# Concurrency with Thread Pools

Many `qontract-reconcile` integrations need to perform the same I/O-bound operation across a large number of independent items, such as fetching data from 50 different clusters or applying a configuration change to 100 different user accounts.

To perform these tasks efficiently, the project uses a standardized pattern of concurrency based on thread pools. This allows the tool to execute many operations in parallel, dramatically reducing the total runtime.

## The `ThreadPoolExecutor`

The primary tool used is Python's `concurrent.futures.ThreadPoolExecutor`. An integration or utility function will typically create a thread pool and submit a series of tasks to it.

## The `defer` Utility

A common way to manage the thread pool is through the `defer` utility (`reconcile.utils.defer.defer`). This function takes a callable (often a lambda) that will be executed when the `defer` block is exited. This is frequently used to ensure the thread pool is properly shut down.

*Example: Applying changes to multiple clusters in parallel*
```python
from concurrent.futures import ThreadPoolExecutor
from reconcile.utils.defer import defer

def run_integration(clusters, thread_pool_size):
    with ThreadPoolExecutor(max_workers=thread_pool_size) as executor:
        # Ensure the executor is shut down cleanly
        defer(executor.shutdown)

        # Submit a task for each cluster to the thread pool
        for cluster in clusters:
            executor.submit(apply_changes_to_cluster, cluster)

def apply_changes_to_cluster(cluster):
    # This function contains the logic for a single cluster.
    # It will be executed in a separate thread.
    # ...
    pass
```

## Where This Pattern is Used

This pattern is fundamental to the performance of `qontract-reconcile` and is used in many key places:

- **`openshift_base.realize_data`**: When applying the desired state, changes to different clusters are often submitted to a thread pool to be processed in parallel.
- **`openshift_base.fetch_current_state`**: The initial fetching of resources from multiple clusters is done concurrently.
- **Integrations with many targets**: Integrations like `terraform-users` or `slack-usergroups` use thread pools to parallelize the process of reconciling hundreds or thousands of individual items.

By using this pattern, developers can write integrations that scale effectively and handle a large volume of resources without becoming a performance bottleneck.
