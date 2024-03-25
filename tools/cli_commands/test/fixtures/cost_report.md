# Cost Report

## Summary

Total AWS Cost for 2024-02: $3,000.00

```json:table
{
  "filter": true,
  "items": [
    {
      "name": "parent",
      "child_apps_total": 2000.0,
      "services_total": 1000.0,
      "total": 3000.0
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

## Cost Breakdown

### child

AWS Services Cost: $2,000.00, +$200.00 (+20.00%) compared to previous month.

```json:table
{
  "filter": true,
  "items": [
    {
      "service": "service2",
      "delta_value": 200.0,
      "delta_percent": 20.0,
      "total": 2000.0
    }
  ],
  "fields": [
    {
      "key": "service",
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
  ]
}
```

### parent

AWS Services Cost: $1,000.00, +$100.00 (+10.00%) compared to previous month.

```json:table
{
  "filter": true,
  "items": [
    {
      "service": "service1",
      "delta_value": 100.0,
      "delta_percent": 10.0,
      "total": 1000.0
    }
  ],
  "fields": [
    {
      "key": "service",
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
  ]
}
```

Child Apps Cost: $2,000.00

```json:table
{
  "filter": true,
  "items": [
    {
      "name": "child",
      "total": 2000.0
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

Total Cost: $3,000.00
