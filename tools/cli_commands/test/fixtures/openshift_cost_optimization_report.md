[TOC]

# OpenShift Cost Optimization Report

Report is generated for optimization enabled namespaces
(`insights_cost_management_optimizations='true'` in namespace `labels`).

In Cost optimizations, recommendations get generated when
CPU usage is at or above the 60th percentile and
memory usage is at the 100th percentile.

View details in [Cost Management Optimizations](https://console.redhat.com/openshift/cost-management/optimizations).

## app

```json:table
{
  "filter": true,
  "items": [
    {
      "namespace": "some-cluster/some-project",
      "workload": "deployment/test-deployment/test",
      "current_cpu_limit": "4",
      "current_cpu_request": "1",
      "current_memory_limit": "5Gi",
      "current_memory_request": "400Mi",
      "recommend_cpu_limit": "5",
      "recommend_cpu_request": "3",
      "recommend_memory_limit": "6Gi",
      "recommend_memory_request": "700Mi"
    }
  ],
  "fields": [
    {
      "key": "namespace",
      "label": "Namespace",
      "sortable": true
    },
    {
      "key": "workload",
      "label": "Workload",
      "sortable": true
    },
    {
      "key": "current_cpu_request",
      "label": "Current CPU Request",
      "sortable": true
    },
    {
      "key": "recommend_cpu_request",
      "label": "Recommend CPU Request",
      "sortable": true
    },
    {
      "key": "current_cpu_limit",
      "label": "Current CPU Limit",
      "sortable": true
    },
    {
      "key": "recommend_cpu_limit",
      "label": "Recommend CPU Limit",
      "sortable": true
    },
    {
      "key": "current_memory_request",
      "label": "Current Memory Request",
      "sortable": true
    },
    {
      "key": "recommend_memory_request",
      "label": "Recommend Memory Request",
      "sortable": true
    },
    {
      "key": "current_memory_limit",
      "label": "Current Memory Limit",
      "sortable": true
    },
    {
      "key": "recommend_memory_limit",
      "label": "Recommend Memory Limit",
      "sortable": true
    }
  ]
}
```
