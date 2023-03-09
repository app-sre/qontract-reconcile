# qontract-reconcile

A qontract-reconcile Helm chart for OpenShift (used to generate OpenShift template)

## Generate OpenShift templates

To generate OpenShift templates from this Helm chart:

1. Update `qontract-reconcile/templates/template.yaml` as required
4. `make generate`

## Install Helm (v3)

https://github.com/helm/helm/releases

## Configuration

| Parameter                   | Description                                                              | Default                            |
|-----------------------------|--------------------------------------------------------------------------|------------------------------------|
| excludeService              | Exclude the Service resource from templating                             | false                              |
| integrations                | List of integration specs to run                                         | `[]`                               |
| cronjobs                    | List of integration specs to run with schedule                           | `[]`                               |

### Integration spec configuration

| Parameter                 | Description                                                              | Default                                                                 |
|---------------------------|--------------------------------------------------------------------------|-------------------------------------------------------------------------|
| cache                     | integration requires cache                                               | false                                                                   |
| command                   | command to run                                                           | qontract-reconcile                                                      |
| disableUnleash            | disable integration interaction with unleash instance                    | false                                                                   |
| environmentAware          | integration requires environment awareness (env vars and env name)       | false                                                                   |
| extraArgs                 | additional arguments to pass to integration                              | []                                                                      |
| extraEnv                  | additional environment variables to set for the integration              | []                                                                      |
| internalCertificates      | integration requires internal certificates to execute                    | false                                                                   |
| logs                      | ship logs to providers                                                   | cloudwatch is enabled by default                                        |
| logs.slack                | ship logs to slack                                                       | false                                                                   |
| logs.googleChat           | ship logs to google chat                                                 | false                                                                   |
| resources                 | CPU/Memory resource requests/limits                                      |                                                                         |
| fluentdResources          | CPU/Memory resource requests/limits for Fluentd                          | {requests: {memory: 30Mi, cpu: 15m}, limits: {memory: 120Mi, cpu: 25m}} |
| saTokenProjection         | include service account token volume projection and env var to path      | false                                                                   |
| shards                    | number of shards to run integration with                                 | 1                                                                       |
| sleepDurationSecs         | time to sleep in seconds between integration executions                  | 600s                                                                    |
| state                     | integration is stateful                                                  | false                                                                   |
| storage                   | size of cache storage                                                    | 1Gi                                                                     |
| trigger                   | integration is an openshift-saas-deploy trigger                          | false                                                                   |
| cron                      | cron expression for integration execution                                | nil                                                                     |
| dashdotdb                 | integration interacts with dashdotdb                                     | false                                                                   |
| concurrencyPolicy         | how to treat concurrent executions of the integration                    | Allow                                                                   |
| restartPolicy             | restarts of the integration                                              | OnFailure                                                               |
| successfulJobHistoryLimit | number of history records reserved for successful integration executions | 3                                                                       |
| failedJobHistoryLimit     | number of history records reserved for failed integration executions     | 1                                                                       |

## Logging

### Usage of "teams" plugin for Google Chat support

Shipping logs (via fluentd sidecar) to Google Chat requires the use of a webhook API and requires a properly constructed payload. After failing to construct the correctly formatted payload with the built-in http fluentd plugin, we searched for another community plugin that would provide general webhook functionality. The Microsoft Teams plugin is poorly named, as the code for said plugin can be used with any general webhook API which accepts json payloads. The app-sre fluentd image was updated to include this plugin, and can be used for applications when a webhook API is being used with fluentd. 
