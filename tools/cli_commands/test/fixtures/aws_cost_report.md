[TOC]

# AWS Cost Report

## Summary

Total AWS Cost for 2024-02: $3,000.00

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
      "child_apps_total": 2000.0,
      "items_total": 1000.0,
      "name": "parent",
      "total": 3000.0
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
      "delta_percent": 20.0,
      "delta_value": 200.0,
      "name": "child",
      "total": 2000.0
    },
    {
      "delta_percent": 10.0,
      "delta_value": 100.0,
      "name": "parent",
      "total": 1000.0
    }
  ]
}
```

## Cost Breakdown

### child

AWS Services Cost: $2,000.00, +$200.00 (+20.00%) compared to previous month.
View in [Cost Management Console](https://console.redhat.com/openshift/cost-management/explorer?dateRangeType=previous_month&filter[limit]=10&filter[offset]=0&filter_by[tag:app]=child&group_by[service]=*&order_by[cost]=desc&perspective=aws).

```json:table
{
  "fields": [
    {
      "key": "name",
      "label": "Service",
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
      "delta_percent": 20.0,
      "delta_value": 200.0,
      "name": "service2",
      "total": 2000.0
    }
  ]
}
```

### parent

AWS Services Cost: $1,000.00, +$100.00 (+10.00%) compared to previous month.
View in [Cost Management Console](https://console.redhat.com/openshift/cost-management/explorer?dateRangeType=previous_month&filter[limit]=10&filter[offset]=0&filter_by[tag:app]=parent&group_by[service]=*&order_by[cost]=desc&perspective=aws).

```json:table
{
  "fields": [
    {
      "key": "name",
      "label": "Service",
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
      "name": "service1",
      "total": 1000.0
    }
  ]
}
```

Child Apps Cost: $2,000.00

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
      "total": 2000.0
    }
  ]
}
```

Total Cost: $3,000.00
