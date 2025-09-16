# The Integration Deployment Model

While integrations are written as Python code, they are deployed and executed as Kubernetes resources (typically `Deployments`, `CronJobs`, or `StatefulSets`) in a production environment. This pattern describes how an integration's definition in `app-interface` is translated into a runnable Kubernetes object.

The `integrations-manager` integration is the engine that drives this entire process.

## The Deployment Workflow

**1. Define the Integration in `app-interface`**

The lifecycle begins with a definition in `app-interface` using a specific schema, like `/app-sre/integration-1.yml`. This definition specifies the integration's properties and where it should run.

*Example: An integration definition file (`/data/integrations/my-integration.yml`)*
```yaml
$schema: /app-sre/integration-1.yml

name: openshift-resources
description: Manages OpenShift resources

managed:
- namespace:
    $ref: /services/app-interface/namespaces/app-interface-stage.yml
  spec:
    resources:
      requests:
        memory: 1Gi
        cpu: 100m
      limits:
        memory: 2Gi
  sharding:
    strategy: static
    shards: 2
```
This definition specifies:
- The integration to run (`openshift-resources`).
- A target namespace for deployment (via a `$ref`).
- Resource requests and limits.
- A sharding strategy (in this case, 2 static shards).

**2. The `integrations-manager` Runs**

The `integrations-manager` is a special integration. Its job is to:
- Query the GraphQL server for all `integrations_v1` definitions.
- For each definition, render the appropriate Kubernetes resource manifests.

**3. Helm Chart Rendering**

The `integrations-manager` uses a built-in Helm chart (`helm/qontract-reconcile/`) to generate the Kubernetes manifests. It translates the `spec` from the `app-interface` definition into Helm values, which determines the kind of resource to create:

- If `spec.cron` is defined, it renders a `CronJob`. This is used for integrations that need to run on a fixed schedule.
- If `spec.state` is `true`, it renders a `StatefulSet`. This is for integrations that require stable, persistent storage.
- Otherwise, the default is to render a `Deployment`, which runs the integration in a continuous reconciliation loop.

The manager also handles complex configurations like **[sharding](./sharding.md)**, where it will generate multiple Kubernetes objects (e.g., multiple `Deployments` or `CronJobs`) from a single `app-interface` definition, each with different parameters to process a specific shard.

**4. Applying the Manifests**

The `integrations-manager` uses the **[OpenShift Resource Management](./openshift-resource-management.md)** pattern to apply the generated manifests to the target cluster.

It populates its `ResourceInventory` with the rendered Kubernetes resources (e.g., `Deployments`, `CronJobs`) as the desired state and then calls `realize_data()`. This ensures that the resource definitions in the cluster are always in sync with their definitions in `app-interface`.

## Summary

This deployment model provides a fully declarative, GitOps-driven way to manage the lifecycle of integrations themselves. Developers only need to define *how* their integration should run in `app-interface`, and the `integrations-manager` handles the rest, ensuring the correct Kubernetes resources are created and kept up-to-date.
