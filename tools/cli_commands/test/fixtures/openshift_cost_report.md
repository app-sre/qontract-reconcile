[TOC]

# OpenShift Cost Report

## Summary

Total OpenShift Cost for 2024-02: $3,300.00

```json:table
{
  "filter": true,
  "items": [
    {
      "name": "parent",
      "child_apps_total": 2200.0,
      "services_total": 1100.0,
      "total": 3300.0
    }
  ],
  "fields": [
    {
      "key": "name",
      "label": "Name",
      "sortable": true
    },
    {
      "key": "services_total",
      "label": "Self App ($)",
      "sortable": true
    },
    {
      "key": "child_apps_total",
      "label": "Child Apps ($)",
      "sortable": true
    },
    {
      "key": "total",
      "label": "Total ($)",
      "sortable": true
    }
  ]
}
```

## Month Over Month Change

Month over month change for 2024-02:

```json:table
{
  "filter": true,
  "items": [
    {
      "name": "child",
      "delta_value": 200.0,
      "delta_percent": 10.0,
      "total": 2200.0
    },
    {
      "name": "parent",
      "delta_value": 100.0,
      "delta_percent": 10.0,
      "total": 1100.0
    }
  ],
  "fields": [
    {
      "key": "name",
      "label": "Name",
      "sortable": true
    },
    {
      "key": "delta_value",
      "label": "Change ($)",
      "sortable": true
    },
    {
      "key": "delta_percent",
      "label": "Change (%)",
      "sortable": true
    },
    {
      "key": "total",
      "label": "Total ($)",
      "sortable": true
    }
  ]
}
```

## Cost Breakdown

### child

OpenShift Workloads Cost: $2,200.00, +$200.00 (+10.00%) compared to previous month.

```json:table
{
  "filter": true,
  "items": [
    {
      "service": "child_cluster/child_namespace",
      "delta_value": 200.0,
      "delta_percent": 10.0,
      "total": 2200.0
    }
  ],
  "fields": [
    {
      "key": "service",
      "label": "Cluster/Namespace",
      "sortable": true
    },
    {
      "key": "delta_value",
      "label": "Change ($)",
      "sortable": true
    },
    {
      "key": "delta_percent",
      "label": "Change (%)",
      "sortable": true
    },
    {
      "key": "total",
      "label": "Total ($)",
      "sortable": true
    }
  ]
}
```

### parent

OpenShift Workloads Cost: $1,100.00, +$100.00 (+10.00%) compared to previous month.

```json:table
{
  "filter": true,
  "items": [
    {
      "service": "parent_cluster/parent_namespace",
      "delta_value": 100.0,
      "delta_percent": 10.0,
      "total": 1100.0
    }
  ],
  "fields": [
    {
      "key": "service",
      "label": "Cluster/Namespace",
      "sortable": true
    },
    {
      "key": "delta_value",
      "label": "Change ($)",
      "sortable": true
    },
    {
      "key": "delta_percent",
      "label": "Change (%)",
      "sortable": true
    },
    {
      "key": "total",
      "label": "Total ($)",
      "sortable": true
    }
  ]
}
```

Child Apps Cost: $2,200.00

```json:table
{
  "filter": true,
  "items": [
    {
      "name": "child",
      "total": 2200.0
    }
  ],
  "fields": [
    {
      "key": "name",
      "label": "Name",
      "sortable": true
    },
    {
      "key": "total",
      "label": "Total ($)",
      "sortable": true
    }
  ]
}
```

Total Cost: $3,300.00
