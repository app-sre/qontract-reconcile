# SLO-Doc Tracking For SLO-metric-data

## Date of Proposal

August 27, 2021

## Terminology

* **SLO-metric-data** - 24-hour-snapshotted data points representing the actual observed values of SLO Prometheus queries. This data is stored in dashdotDB's underlying Postgres database.

* **SLO-document** - Resources stored as app-interface data, and associated with services. [Example](https://gitlab.cee.redhat.com/service/app-interface/-/blob/32d546477e729e07bf33a46edce8ec44e6009e56/data/services/cincinnati/slo-documents/cincinnati.yml)

* **SLO-definition** - SLOs as defined in any 'SLO-document'. [Example](https://gitlab.cee.redhat.com/service/app-interface/-/blob/32d546477e729e07bf33a46edce8ec44e6009e56/data/services/cincinnati/slo-documents/cincinnati.yml#L13-23)

## Tracking

Implementation is tracked through [this Jira ticket](https://issues.redhat.com/browse/APPSRE-3570).

For a high-level overview of the problem this proposal aims to address, in the context of the wholistic App-SRE toolset (dashdotDB, app-interface, qontract-reconcile, visual-qontract, etc), please see [this Jira comment](https://issues.redhat.com/browse/APPSRE-3570?focusedCommentId=18878164&page=com.atlassian.jira.plugin.system.issuetabpanels%3Acomment-tabpanel#comment-18878164).

## Problem

TODO

## Proposal

TODO

## Implementation - Storing SLO Metric Data

TODO

## Implementation - Producing Service Reports

TODO
