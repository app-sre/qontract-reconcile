[TOC]

# OpenShift Cost Report

## Summary

Total OpenShift Cost for 2024-02: $3,300.00

```json:table
{
  "fields": [
    {
      "key": "name",
      "label": "Name",
      "sortable": true
    },
    {
      "key": "items_total",
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
  ],
  "filter": true,
  "items": [
    {
      "child_apps_total": 2200.0,
      "items_total": 1100.0,
      "name": "parent",
      "total": 3300.0
    }
  ]
}
```

## Month Over Month Change

Month over month change for 2024-02:

```json:table
{
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
  ],
  "filter": true,
  "items": [
    {
      "delta_percent": 10.0,
      "delta_value": 200.0,
      "name": "child",
      "total": 2200.0
    },
    {
      "delta_percent": 10.0,
      "delta_value": 100.0,
      "name": "parent",
      "total": 1100.0
    }
  ]
}
```

## Cost Breakdown

### child

OpenShift Workloads Cost: $2,200.00, +$200.00 (+10.00%) compared to previous month.

```json:table
{
  "fields": [
    {
      "key": "name",
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
  ],
  "filter": true,
  "items": [
    {
      "delta_percent": 10.0,
      "delta_value": 200.0,
      "name": "child_cluster/child_namespace",
      "total": 2200.0
    }
  ]
}
```

### parent

OpenShift Workloads Cost: $1,100.00, +$100.00 (+10.00%) compared to previous month.

```json:table
{
  "fields": [
    {
      "key": "name",
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
  ],
  "filter": true,
  "items": [
    {
      "delta_percent": 10.0,
      "delta_value": 100.0,
      "name": "parent_cluster/parent_namespace",
      "total": 1100.0
    }
  ]
}
```

Child Apps Cost: $2,200.00

```json:table
{
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
  ],
  "filter": true,
  "items": [
    {
      "name": "child",
      "total": 2200.0
    }
  ]
}
```

Total Cost: $3,300.00
