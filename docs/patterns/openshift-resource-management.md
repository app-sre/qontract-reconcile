# OpenShift Resource Management

A large number of integrations in `qontract-reconcile` are designed to manage resources within OpenShift or Kubernetes clusters. To ensure this is done consistently and safely, the project provides a standardized pattern for OpenShift resource management.

This pattern abstracts away the complexities of the OpenShift API and provides a declarative, idempotent way to enforce the desired state of any resource kind.

## The Core Components

This pattern revolves around two key utility classes and a set of helper functions found in `reconcile/openshift_base.py`.

*   **`OpenshiftResource`**: A generic wrapper class for any Kubernetes/OpenShift resource (e.g., a `Deployment`, `Service`, `Route`). It holds the resource body and combines it with metadata from `app-interface` to create a desired state representation.
*   **`ResourceInventory`**: An object that holds the state of all resources for a given reconciliation run. It maintains two separate inventories: one for the *desired state* (from `app-interface`) and one for the *current state* (from the live cluster).

## The Reconciliation Workflow

Integrations that manage OpenShift resources follow this specific workflow, which extends the [core reconciliation loop](./reconciliation-loop.md):

**1. Fetch Current State from Clusters**

The first step is to populate the `ResourceInventory` with the current state of all relevant resources from the target OpenShift clusters. The `openshift_base.fetch_current_state()` function handles this, using an `OC_Map` ([Client Factory](./client-factories.md) pattern) to manage cluster connections.

```python
# from reconcile import openshift_base as ob

# ri is the ResourceInventory
# oc_map is a map of OpenShift clients
ri, oc_map = ob.fetch_current_state(
    namespaces=list_of_namespaces,
    thread_pool_size=thread_pool_size,
    integration=QONTRACT_INTEGRATION,
    # Specify which resource types to fetch
    override_managed_types=['Deployment', 'Service', 'Route']
)
```

**2. Fetch Desired State from `app-interface`**

Next, the integration fetches its desired state from `app-interface` (usually via a `qenerate` query) and populates the `ResourceInventory` with the desired resources.

Each resource is wrapped in an `OpenshiftResource` object and added to the inventory's desired state.

```python
from reconcile.utils.openshift_resource import OpenshiftResource

# Logic to get desired resources from app-interface
desired_deployments = get_my_deployments()

for deployment_body in desired_deployments:
    # Create the wrapper object
    resource = OpenshiftResource(
        body=deployment_body,
        integration=QONTRACT_INTEGRATION,
        integration_version=QONTRACT_INTEGRATION_VERSION
    )
    # Add it to the inventory
    ri.add_desired(
        cluster='my-cluster',
        namespace='my-namespace',
        kind=resource.kind,
        name=resource.name,
        value=resource
    )
```

**3. Publish Metrics (Optional)**

The `ResourceInventory` can automatically generate Prometheus metrics about the number of desired and current resources.

```python
ob.publish_metrics(ri, QONTRACT_INTEGRATION)
```

**4. Realize the Data (Act)**

This is the final and most critical step. The `openshift_base.realize_data()` function takes the `ResourceInventory` and executes the reconciliation logic.

It compares the desired and current states for every resource and automatically calculates and applies the necessary actions (create, update, or delete) to align the cluster state with the desired state.

```python
ob.realize_data(
    dry_run=dry_run,
    oc_map=oc_map,
    ri=ri,
    thread_pool_size=thread_pool_size
)
```

This function transparently handles the `--dry-run` flag. In dry-run mode, it will only print the API calls it *would* make. In a "wet" run, it executes them. This provides a powerful and safe mechanism for managing thousands of resources across many clusters.
