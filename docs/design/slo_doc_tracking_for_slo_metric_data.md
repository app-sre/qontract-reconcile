# SLO-Doc Tracking For SLO-metric-data

## Date of Proposal

September 7, 2021

## Terminology

* **SLO-metric-data** - 24-hour-snapshotted data points representing the actual observed values of SLO Prometheus queries. This data is produced by a qontract-reconcile integration, and is stored in dashdotDB's underlying Postgres database.

* **SLO-document** - Resources stored as app-interface data, and associated with services. [Example](https://gitlab.cee.redhat.com/service/app-interface/-/blob/32d546477e729e07bf33a46edce8ec44e6009e56/data/services/cincinnati/slo-documents/cincinnati.yml)

* **SLO-definition** - SLOs as defined in any 'SLO-document'. [Example](https://gitlab.cee.redhat.com/service/app-interface/-/blob/32d546477e729e07bf33a46edce8ec44e6009e56/data/services/cincinnati/slo-documents/cincinnati.yml#L13-23)

## Tracking

Implementation is tracked through [this Jira ticket](https://issues.redhat.com/browse/APPSRE-3570).

For a high-level overview of the problem this proposal aims to address, in the context of the wholistic App-SRE toolset (dashdotDB, app-interface, qontract-reconcile, visual-qontract, etc), please see [this Jira comment](https://issues.redhat.com/browse/APPSRE-3570?focusedCommentId=18878164&page=com.atlassian.jira.plugin.system.issuetabpanels%3Acomment-tabpanel#comment-18878164).

## Problem

qontract-reconcile produces [reports](https://gitlab.cee.redhat.com/service/app-interface/-/tree/master/data/reports) on services. Within these reports are SLO-metric-data ([example](https://gitlab.cee.redhat.com/service/app-interface/-/blob/master/data/reports/ocm/2021-08-01.yml#L128-143)).

A service may have multiple SLO-definitions with the same 'name', but spread across multiple SLO-documents. The reports produced by qontract-reconcile do not produce 'service_slo' YML data in such a way that multiples SLOs with the same name will be distinguishable.

A sample YML snippet of a SLO-report's 'service_slo' appears today as follows:
```yml
service_slo:
  - cluster: cluster1
    namespace: some-namespace
    slo_name: availability
    slo_value: 99.0
    slo_target: 95.0
  - cluster: cluster2
    namespace: some-namespace
    slo_name: latency
    slo_value: 99.0
    slo_target: 95.0
```

## Proposal

## Implementation - Storing SLO Metric Data

[This proposal for dashdotDB](https://github.com/app-sre/dashdotdb/pull/51) would enable clients of dashdotDB's HTTP API to associate an SLO-doc-name with SLO-metric-data uploads via `POST /api/v1/serviceslometrics/{name}`.

qontract-reconcile currently consumes this API as part of the [dashdotdb-slo integration](https://github.com/app-sre/qontract-reconcile/blob/master/reconcile/dashdotdb_slo.py).

Should the dashdotDB proposal be implemented, qontract-reconcile must be updated to include 'slo_doc.name' in the request body for requests to the aforementioned API, as it becomes a required property.

## Implementation - Producing Service Reports

[This proposal for dashdotDB](https://github.com/app-sre/dashdotdb/pull/51) would enable clients of dashdotDB's HTTP API to associate an SLO-doc-name with SLO-metric-data reads via `GET /api/v1/serviceslometrics/metrics`.

qontract-reconcile currently consumes this API as part of the [app-interface-reporter process](https://github.com/app-sre/qontract-reconcile/blob/master/tools/app_interface_reporter.py).

Should the dashdotDB proposal be implemented, qontract-reconcile will be updated to produce reports with a 'service_slo' property that would appear as follows:
```yml
service_slo:
  - cluster: cluster1
    namespace: some-namespace
    slo_doc_name: doc1
    slo_name: availability
    slo_value: 99.0
    slo_target: 95.0
  - cluster: cluster2
    namespace: some-namespace
    slo_doc_name: doc2
    slo_name: latency
    slo_value: 99.0
    slo_target: 95.0
```
