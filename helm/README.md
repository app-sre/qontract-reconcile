# qontract-reconcile

A qontract-reconcile Helm chart for OpenShift (used to generate OpenShift template)

## Generate OpenShift templates

To generate OpenShift templates from this Helm chart:

1. Update `qontract-reconcile/templates/templates.yaml` as required
2. Update `qontract-reconcile/values-external.yaml` as required
3. Update `qontract-reconcile/values-internal.yaml` as required
4. `make generate`

## Install Helm (v3)

https://github.com/helm/helm/releases
