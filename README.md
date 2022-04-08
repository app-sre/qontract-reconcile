![build](https://ci.ext.devshift.net/buildStatus/icon?job=app-sre-qontract-reconcile-gh-build-master)
![license](https://img.shields.io/github/license/app-sre/qontract-reconcile.svg?style=flat)

# qontract-reconcile

A tool to reconcile services with their desired state as defined in App-Interface.
In addition, e2e tests are available to detect potential problems reconciling services with their desired state.
Additional tools that use the libraries created by the reconciliations are also hosted here.

## Subcommands

### qontract-reconcile

```
  aws-ami-share                   Share AMI and AMI tags between accounts.
  aws-ecr-image-pull-secrets      Generate AWS ECR image pull secrets and
                                  store them in Vault.
  aws-garbage-collector           Delete orphan AWS resources.
  aws-iam-keys                    Delete IAM access keys by access key ID.
  aws-iam-password-reset          Reset IAM user password by user reference.
  aws-support-cases-sos           Scan AWS support cases for reports of leaked
                                  keys and remove them (only submits PR)
  blackbox-exporter-endpoint-monitoring
                                  Manages Prometheus Probe resources for
                                  blackbox-exporter
  cluster-deployment-mapper       Maps ClusterDeployment resources to Cluster
                                  IDs.
  dashdotdb-cso                   Collects the ImageManifestVuln CRs from all
                                  the clusters and posts them to Dashdotdb.
  dashdotdb-dvo                   Collects the DeploymentValidations from all
                                  the clusters and posts them to Dashdotdb.
  dashdotdb-slo                   Collects the ServiceSloMetrics from all the
                                  clusters and posts them to Dashdotdb.
  dyn-traffic-director            Manage Traffic Director services in Dyn DNS.
  ecr-mirror                      Mirrors external images into AWS ECR.
  email-sender                    Send email notifications to app-interface
                                  audience.
  gabi-authorized-users           Manages user access for GABI instances.
  gcr-mirror                      Mirrors external images into Google
                                  Container Registry.
  github                          Configures the teams and members in a GitHub
                                  org.
  github-owners                   Configures owners in a GitHub org.
  github-repo-invites             Accept GitHub repository invitations for
                                  known repositories.
  github-repo-permissions-validator
                                  Validates permissions in github
                                  repositories.
  github-scanner                  Scan GitHub repositories for leaked keys and
                                  remove them (only submits PR).
  github-users                    Validate compliance of GitHub user profiles.
  github-validator                Validates GitHub organization settings.
  gitlab-ci-skipper               Determines if CI can be skipped.
  gitlab-fork-compliance          Ensures that forks of App Interface are
                                  compliant.
  gitlab-housekeeping             Manage issues and merge requests on GitLab
                                  projects.
  gitlab-integrations             Manage integrations on GitLab projects.
  gitlab-labeler                  Guesses and adds labels to merge requests
                                  according to changed paths.
  gitlab-members                  Manage GitLab group members.
  gitlab-mr-sqs-consumer          Listen to SQS and creates MRs out of the
                                  messages.
  gitlab-owners                   Manages labels on gitlab merge requests
                                  based on OWNERS files schema.
  gitlab-permissions              Manage permissions on GitLab projects.
  gitlab-projects                 Create GitLab projects.
  integrations-validator          Ensures all integrations are defined in App-
                                  Interface.
  jenkins-job-builder             Manage Jenkins jobs configurations using
                                  jenkins-jobs.
  jenkins-job-builds-cleaner      Clean up jenkins job history.
  jenkins-job-cleaner             Delete Jenkins jobs in multiple tenant
                                  instances.
  jenkins-plugins                 Manage Jenkins plugins installation via REST
                                  API.
  jenkins-roles                   Manage Jenkins roles association via REST
                                  API.
  jenkins-webhooks                Manage web hooks to Jenkins jobs.
  jenkins-webhooks-cleaner        Remove webhooks to previous Jenkins
                                  instances.
  jira-watcher                    Watch for changes in Jira boards and notify
                                  on Slack.
  kafka-clusters                  Manages Kafka clusters via OCM.
  ldap-users                      Removes users which are not found in LDAP
                                  search.
  ocm-additional-routers          Manage additional routers in OCM.
  ocm-addons                      Manages cluster Addons in OCM.
  ocm-aws-infrastructure-access   Grants AWS infrastructure access to members
                                  in AWS groups via OCM.
  ocm-clusters                    Manages clusters via OCM.
  ocm-external-configuration-labels
                                  Manage External Configuration labels in OCM.
  ocm-github-idp                  Manage GitHub Identity Providers in OCM.
  ocm-groups                      Manage membership in OpenShift groups via
                                  OCM.
  ocm-machine-pools               Manage Machine Pools in OCM.
  ocm-upgrade-scheduler           Manage Upgrade Policy schedules in OCM.
  ocp-release-mirror              Mirrors OCP release images.
  openshift-clusterrolebindings   Configures ClusterRolebindings in OpenShift
                                  clusters.
  openshift-groups                Manages OpenShift Groups.
  openshift-limitranges           Manages OpenShift LimitRange objects.
  openshift-namespace-labels      Manages labels on OpenShift namespaces.
  openshift-namespaces            Manages OpenShift Namespaces.
  openshift-network-policies      Manages OpenShift NetworkPolicies.
  openshift-resourcequotas        Manages OpenShift ResourceQuota objects.
  openshift-resources             Manages OpenShift Resources.
  openshift-rolebindings          Configures Rolebindings in OpenShift
                                  clusters.
  openshift-routes                Manages OpenShift Routes.
  openshift-saas-deploy           Manage OpenShift resources defined in Saas
                                  files.
  openshift-saas-deploy-trigger-cleaner
                                  Clean up deployment related resources.
  openshift-saas-deploy-trigger-configs
                                  Trigger deployments when configuration
                                  changes.
  openshift-saas-deploy-trigger-moving-commits
                                  Trigger deployments when a commit changed
                                  for a ref.
  openshift-saas-deploy-trigger-upstream-jobs
                                  Trigger deployments when upstream job runs.
  openshift-saas-deploy-wrapper   A wrapper around openshift-saas-deploy.
  openshift-serviceaccount-tokens
                                  Use OpenShift ServiceAccount tokens across
                                  namespaces/clusters.
  openshift-tekton-resources      Manages custom resources for Tekton based
                                  deployments.
  openshift-upgrade-watcher       Watches for OpenShift upgrades and sends
                                  notifications.
  openshift-users                 Deletion of users from OpenShift clusters.
  openshift-vault-secrets         Manages OpenShift Secrets from Vault.
  osd-mirrors-data-updater        Collects OSD mirror information and updates
                                  app-interface via MR.
  prometheus-rules-tester         Tests prometheus rules using promtool.
  quay-membership                 Configures the teams and members in Quay.
  quay-mirror                     Mirrors external images into Quay.
  quay-mirror-org                 Mirrors entire Quay orgs.
  quay-permissions                Manage permissions for Quay Repositories.
  quay-repos                      Creates and Manages Quay Repos.
  requests-sender                 Send emails to users based on requests
                                  submitted to app-interface.
  saas-file-owners                Manages labels on merge requests based on
                                  approver schema for saas files.
  saas-file-validator             Validates Saas files.
  sendgrid-teammates              Manages SendGrid teammates for a given
                                  account.
  sentry-config                   Configure and enforce sentry instance
                                  configuration.
  sentry-helper                   Watch for Sentry access requests and notify
                                  on Slack.
  service-dependencies            Validate dependencies are defined for each
                                  service.
  signalfx-prometheus-endpoint-monitoring
                                  Manages Prometheus Probe resources for
                                  signalfx exporter
  slack-cluster-usergroups        Manage Slack User Groups (channels and
                                  users) for OpenShift users notifications.
  slack-usergroups                Manage Slack User Groups (channels and
                                  users).
  sql-query                       Runs SQL Queries against app-interface RDS
                                  resources.
  status-page-components          Manages components on statuspage.io hosted
                                  status pages.
  terraform-aws-route53           Manage AWS Route53 resources using
                                  Terraform.
  terraform-resources             Manage AWS Resources using Terraform.
  terraform-resources-wrapper     A wrapper around terraform-resources.
  terraform-tgw-attachments       Manages Transit Gateway attachments.
  terraform-users                 Manage AWS users using Terraform.
  terraform-vpc-peerings          Manage VPC peerings between OSD clusters and
                                  AWS accounts or other OSD clusters.
  unleash-watcher                 Watch for changes in Unleah feature toggles
                                  and notify on Slack.
  user-validator                  Validate user files.
```

### e2e-tests

- `create-namespace`: A test to create a namespace and verify that required `RoleBinding`s are created as well to be able to reconcile them.
- `dedicated-admin-rolebindings`: A test to verify that all required namespaces have the required `RoleBinding`s to be able to reconcile them.

### tools

- `app-interface-reporter`: Creates service reports and submits PR to App-Interface.
- `qontract-cli`: A cli tool for qontract (currently very good at getting information).

## Usage

Use [config.toml.example](config.toml.example) as a template to create a `config.toml` file.

Run a reconcile integration like this:

```sh
qontract-reconcile --config config.toml --dry-run <subcommand>

# review output and run without `--dry-run` to perform actual changes
qontract-reconcile --config config.toml <subcommand>
```

> Note: you can use the `QONTRACT_CONFIG` environment variable instead of using `--config`.

## OpenShift usage

OpenShift templates can be found [here](/openshift/qontract-reconcile.yaml). In order to add integrations there please use the [helm](/helm/README.md) chart provided.

## Installation

This project targets Python version 3.9.x for best compatibility. Verify the Python3 version that your shell is using with `python3 --version`. You can optionally use a tool like [pyenv](https://github.com/pyenv/pyenv) to manage Python versions on your computer.

Create and enter the [virtualenv](https://virtualenv.pypa.io/en/latest/) environment:

```sh
python3 -m venv venv
source venv/bin/activate

# make sure you are running the latest setuptools
pip install --upgrade pip setuptools
```

Install the package:

```sh
pip install .

# or use this for development mode so rebuild/reinstall isn't necessary after 
# each change that is made during development
pip install -e .

# optionally install all test/type dependencies - useful when writing tests,
# auto-completion in your IDE, etc.
pip install -r ./requirements/requirements-dev.txt
```

If the commands above don't work maybe you need to install the `python-devel` and `gcc-c++` packages.
You may also need need to first [install a rust compiler](https://www.rust-lang.org/tools/install) ([Mac OS directions](https://sourabhbajaj.com/mac-setup/Rust/)) and then run `python3 -m pip install --upgrade pip setuptools_rust`.

### Requirements

Please see [setup.py](setup.py).

All requirements files are gathered in [./requirements/](./requirements).
It consists of:

- [requirements-test.txt](requirements/requirements-test.txt) for unit test and linting dependencies
- [requirements-type.txt](requirements/requirements-type.txt) for type checking dependencies
- [requirements-format.txt](requirements/requirements-format.txt) for formatting dependencies
- [requirements-dev.txt](requirements/requirements-dev.txt) installs all above mentioned dependencies

### Image build

In order to speed up frequent builds and avoid issues with dependencies, docker image makes use
[`qontract-reconcile-build`](https://quay.io/repository/app-sre/qontract-reconcile-base?tag=latest&tab=tags)
image. See [`app-sre/coontainer-images`](https://github.com/app-sre/container-images) repository
if you want to make changes to the base image. This repo [`Dockerfile`](dockerfiles/Dockerfile)
must only contain instructions related to the python code build.

## CI Tooling

This project uses [tox](https://tox.readthedocs.io/en/latest/) for running 
tests, linting/static analysis, and type checkers. Some of the more common 
commands have been provided below, but see the tox docs for more complete 
documentation.

Running all checks (tests, linting, and type checkers):

```
tox
```

To run the checks faster (run in parallel):

```
tox -p
```

Running specific checks (can be much faster):

```
# Only run unit tests using Python 3.6
tox -e py36

# Only run linters
tox -e lint

# Only run the type checker
tox -e type

# Look at tox.ini for usage of posargs, this allows us to override which 
# options are passed to the CLI where it's being used. This can be helpful 
# for type checking a specific file, or running a subset of unit tests (this  
# can be even faster).
tox -e type -- reconcile/utils/slack_api.py
```

## Run reconcile loop for an integration locally in a container

 This is currently only tested with the docker container engine.

### Prepare config.toml

Make sure the file `./config.dev.toml` exists and contains your current configuration.
Your `config.dev.toml` should point to the following qontract-server address:

```
[graphql]
server = "http://host.docker.internal:4000/graphql"
```

### Run qontract-server

Start the [qontract-server](https://github.com/app-sre/qontract-server) in a different window, e.g., via:

```
qontract-server$ make dev
```

### Trigger integration

```
make dev-reconcile-loop INTEGRATION_NAME=terraform-resources DRY_RUN=--dry-run INTEGRATION_EXTRA_ARGS=--light SLEEP_DURATION_SECS=100
```

## Release

Release version are calculated from git tags of the form X.Y.Z.
- If the current commit has such a tag, it will be used as is
- Otherwise the latest tag of that format is used and:
  - the patch label (Z) is incremented
  - the string `.pre<count>+<commitid>` is appended. `<count>` is the number of commits since the X.Y.Z tag. `<commitid> is... the current commitid.

After the PR is merged, a CI job will be triggered that will publish the package to pypi: https://pypi.org/project/qontract-reconcile.

## Licence

[Apache License Version 2.0](LICENSE).

## Authors

These tools have been written by the [Red Hat App-SRE Team](mailto:sd-app-sre@redhat.com).
