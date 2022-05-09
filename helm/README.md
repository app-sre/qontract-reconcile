# qontract-reconcile

A qontract-reconcile Helm chart for OpenShift (used to generate OpenShift template)

## Generate OpenShift templates

To generate OpenShift templates from this Helm chart:

1. Update `qontract-reconcile/templates/template.yaml` as required
2. Update `qontract-reconcile/values-external.yaml` as required
3. Update `qontract-reconcile/values-internal.yaml` as required
4. `make generate`

## Install Helm (v3)

https://github.com/helm/helm/releases

## Configuration

| Parameter                   | Description                                                              | Default                            |
|-----------------------------|--------------------------------------------------------------------------|------------------------------------|
| integrations                | List of integration specs to run                                         | `[]`                               |
| cronjobs                    | List of integration specs to run with schedule                           | `[]`                               |

### Integration spec configuration

| Parameter                   | Description                                                              | Default                            |
|-----------------------------|--------------------------------------------------------------------------|------------------------------------|
| cache                       | integration requires cache                                               | false                              |
| command                     | command to run                                                           | qontract-reconcile                 |
| disableUnleash              | disable integration interaction with unleash instance                    | false                              |
| extraArgs                   | additional arguments to pass to integration                              | []                                 |
| extraEnv                    | additional environment variables to set for the integration              | []                                 |
| internalCertificates        | integration requires internal certificates to execute                    | false                              |
| logs                        | ship logs to providers                                                   | cloudwatch is enabled by default   |
| logs.slack                  | ship logs to slack                                                       | false                              |
| resources                   | CPU/Memory resource requests/limits                                      |                                    |
| shards                      | number of shards to run integration with                                 | 1                                  |
| sleepDurationSecs           | time to sleep in seconds between integration executions                  | 600s                               |
| state                       | integration is stateful                                                  | false                              |
| storage                     | size of cache storage                                                    | 1Gi                                |
| trigger                     | integration is an openshift-saas-deploy trigger                          | false                              |
| cron                        | cron expression for integration execution                                | nil                                |
| dashdotdb                   | integration interacts with dashdotdb                                     | false                              |
| concurrencyPolicy           | how to treat concurrent executions of the integration                    | Allow                              |
| restartPolicy               | restarts of the integration                                              | OnFailure                          |
| successfulJobHistoryLimit   | number of history records reserved for successful integration executions | 3                                  |
| failedJobHistoryLimit       | number of history records reserved for failed integration executions     | 1                                  |
