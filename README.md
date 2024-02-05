![build](https://ci.ext.devshift.net/buildStatus/icon?job=app-sre-qontract-reconcile-gh-build-master)
![license](https://img.shields.io/github/license/app-sre/qontract-reconcile.svg?style=flat)

# qontract-reconcile

A tool to reconcile services with their desired state as defined in App-Interface.
Additional tools that use the libraries created by the reconciliations are also hosted here.

## Subcommands

### qontract-reconcile

```text
  acs-policies                    Manages RHACS security policy configurations
  acs-rbac                        Manages RHACS rbac configuration
  advanced-upgrade-scheduler      Manage Cluster Upgrade Policy schedules in
                                  OCM organizations based on OCM labels.
  aws-ami-cleanup                 Cleanup old and unused AMIs.
  aws-ami-share                   Share AMI and AMI tags between accounts.
  aws-cloudwatch-log-retention    Set up retention period for Cloudwatch logs.
  aws-ecr-image-pull-secrets      Generate AWS ECR image pull secrets and
                                  store them in Vault.
  aws-garbage-collector           Delete orphan AWS resources.
  aws-iam-keys                    Delete IAM access keys by access key ID.
  aws-iam-password-reset          Reset IAM user password by user reference.
  aws-saml-idp                    Manage the SAML IDP config for all AWS
                                  accounts.
  aws-saml-roles                  Manage the SAML IAM roles for all AWS
                                  accounts with SSO enabled
  aws-support-cases-sos           Scan AWS support cases for reports of leaked
                                  keys and remove them (only submits PR)
  aws-version-sync                Sync AWS asset version numbers to App-
                                  Interface
  blackbox-exporter-endpoint-monitoring
                                  Manages Prometheus Probe resources for
                                  blackbox-exporter
  change-owners                   Detects owners for changes in app-interface
                                  PRs and allows them to self-service merge.
  cluster-deployment-mapper       Maps ClusterDeployment resources to Cluster
                                  IDs.
  cna-resources                   Manage Cloud Resources using Cloud Native
                                  Assets (CNA).
  dashdotdb-cso                   Collects the ImageManifestVuln CRs from all
                                  the clusters and posts them to Dashdotdb.
  dashdotdb-dora                  Collects dora metrics.
  dashdotdb-dvo                   Collects the DeploymentValidations from all
                                  the clusters and posts them to Dashdotdb.
  dashdotdb-slo                   Collects the ServiceSloMetrics from all the
                                  clusters and posts them to Dashdotdb.
  database-access-manager         Manage Databases and Database Users.
  dynatrace-token-provider        Automatically provide dedicated Dynatrace
                                  tokens to management clusters
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
  github-users                    Validate compliance of GitHub user profiles.
  github-validator                Validates GitHub organization settings.
  gitlab-fork-compliance          Ensures that forks of App Interface are
                                  compliant.
  gitlab-housekeeping             Manage issues and merge requests on GitLab
                                  projects.
  gitlab-labeler                  Guesses and adds labels to merge requests
                                  according to changed paths.
  gitlab-members                  Manage GitLab group members.
  gitlab-mr-sqs-consumer          Listen to SQS and creates MRs out of the
                                  messages.
  gitlab-owners                   Manages labels on gitlab merge requests
                                  based on OWNERS files schema.
  gitlab-permissions              Manage permissions on GitLab projects.
  gitlab-projects                 Create GitLab projects.
  glitchtip                       Configure and enforce glitchtip instance
                                  configuration.
  glitchtip-project-alerts        Configure Glitchtip project alerts.
  glitchtip-project-dsn           Glitchtip project dsn as openshift secret.
  integrations-manager            Manages Qontract Reconcile integrations.
  jenkins-job-builder             Manage Jenkins jobs configurations using
                                  jenkins-jobs.
  jenkins-job-builds-cleaner      Clean up jenkins job history.
  jenkins-job-cleaner             Delete Jenkins jobs in multiple tenant
                                  instances.
  jenkins-roles                   Manage Jenkins roles association via REST
                                  API.
  jenkins-webhooks                Manage web hooks to Jenkins jobs.
  jenkins-webhooks-cleaner        Remove webhooks to previous Jenkins
                                  instances.
  jenkins-worker-fleets           Manage Jenkins worker fleets via JCasC.
  jira-permissions-validator      Validate permissions in Jira.
  jira-watcher                    Watch for changes in Jira boards and notify
                                  on Slack.
  ldap-groups                     Manages LDAP groups based on App-Interface
                                  roles.
  ldap-users                      Removes users which are not found in LDAP
                                  search.
  ocm-additional-routers          Manage additional routers in OCM.
  ocm-addons                      Manages cluster Addons in OCM.
  ocm-addons-upgrade-scheduler-org
                                  Manage Addons Upgrade Policy schedules in
                                  OCM organizations.
  ocm-addons-upgrade-tests-trigger
                                  Trigger jenkins jobs following Addon
                                  upgrades.
  ocm-aws-infrastructure-access   Grants AWS infrastructure access to members
                                  in AWS groups via OCM.
  ocm-clusters                    Manages clusters via OCM.
  ocm-external-configuration-labels
                                  Manage External Configuration labels in OCM.
  ocm-github-idp                  Manage GitHub Identity Providers in OCM.
  ocm-groups                      Manage membership in OpenShift groups via
                                  OCM.
  ocm-internal-notifications      Notifications to internal Red Hat users
                                  based on conditions in OCM.
  ocm-labels                      Manage cluster OCM labels.
  ocm-machine-pools               Manage Machine Pools in OCM.
  ocm-oidc-idp                    Manage OIDC cluster configuration in OCM
                                  organizations based on OCM labels. Part of
                                  RHIDP.
  ocm-standalone-user-management  Manages OCM cluster usergroups and
                                  notifications via OCM labels.
  ocm-update-recommended-version  Update recommended version for OCM orgs
  ocm-upgrade-scheduler-org       Manage Upgrade Policy schedules in OCM
                                  organizations.
  ocm-upgrade-scheduler-org-updater
                                  Update Upgrade Policy schedules in OCM
                                  organizations.
  openshift-cluster-bots          Manages dedicated-admin and cluster-admin
                                  creds.
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
  openshift-saas-deploy-change-tester
                                  Runs openshift-saas-deploy for each saas-
                                  file that changed within a bundle.
  openshift-saas-deploy-trigger-cleaner
                                  Clean up deployment related resources.
  openshift-saas-deploy-trigger-configs
                                  Trigger deployments when configuration
                                  changes.
  openshift-saas-deploy-trigger-images
                                  Trigger deployments when images are pushed.
  openshift-saas-deploy-trigger-moving-commits
                                  Trigger deployments when a commit changed
                                  for a ref.
  openshift-saas-deploy-trigger-upstream-jobs
                                  Trigger deployments when upstream job runs.
  openshift-serviceaccount-tokens
                                  Use OpenShift ServiceAccount tokens across
                                  namespaces/clusters.
  openshift-tekton-resources      Manages custom resources for Tekton based
                                  deployments.
  openshift-upgrade-watcher       Watches for OpenShift upgrades and sends
                                  notifications.
  openshift-users                 Deletion of users from OpenShift clusters.
  openshift-vault-secrets         Manages OpenShift Secrets from Vault.
  prometheus-rules-tester         Tests prometheus rules using promtool.
  quay-membership                 Configures the teams and members in Quay.
  quay-mirror                     Mirrors external images into Quay.
  quay-mirror-org                 Mirrors entire Quay orgs.
  quay-permissions                Manage permissions for Quay Repositories.
  quay-repos                      Creates and Manages Quay Repos.
  query-validator                 Validate queries to maintain consumer schema
                                  compatibility.
  requests-sender                 Send emails to users based on requests
                                  submitted to app-interface.
  resource-scraper                Get resources from clusters and store in
                                  Vault.
  resource-template-tester        Tests templating of resources.
  rhidp-sso-client                Manage Keycloak SSO clients for OCM
                                  clusters. Part of RHIDP.
  saas-auto-promotions-manager    Manage auto-promotions defined in SaaS files
  saas-file-validator             Validates Saas files.
  sendgrid-teammates              Manages SendGrid teammates for a given
                                  account.
  service-dependencies            Validate dependencies are defined for each
                                  service.
  signalfx-prometheus-endpoint-monitoring
                                  Manages Prometheus Probe resources for
                                  signalfx exporter
  skupper-network                 Manages Skupper Networks.
  slack-usergroups                Manage Slack User Groups (channels and
                                  users).
  sql-query                       Runs SQL Queries against app-interface RDS
                                  resources.
  status-board-exporter           Export Product and Application informnation
                                  to Status Board.
  status-page-components          Manages components on statuspage.io hosted
                                  status pages.
  terraform-aws-route53           Manage AWS Route53 resources using
                                  Terraform.
  terraform-cloudflare-dns        Manage Cloudflare DNS using Terraform.
  terraform-cloudflare-resources  Manage Cloudflare Resources using Terraform.
  terraform-cloudflare-users      Manage Cloudflare Users using Terraform.
  terraform-repo                  Manages raw HCL Terraform from a separate
                                  repository.
  terraform-resources             Manage AWS Resources using Terraform.
  terraform-tgw-attachments       Manages Transit Gateway attachments.
  terraform-users                 Manage AWS users using Terraform.
  terraform-vpc-peerings          Manage VPC peerings between OSD clusters and
                                  AWS accounts or other OSD clusters.
  vault-replication               Allow vault to replicate secrets to other
                                  instances.
  vpc-peerings-validator          Validates that VPC peerings do not exist
                                  between public and internal clusters.
```

### tools

- `app-interface-metrics-exporter`: Exports metrics from App-Interface.
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

This project targets Python version 3.11.x for best compatibility. Verify the Python3 version that your shell is using with `python3 --version`. You can optionally use a tool like [pyenv](https://github.com/pyenv/pyenv) or [asdf](https://asdf-vm.com/) to manage Python versions on your computer.

Create and enter the [virtualenv](https://virtualenv.pypa.io/en/latest/) environment:

```sh
python3 -m venv venv
source venv/bin/activate

# make sure you are running the latest setuptools
pip install --upgrade pip setuptools
```

Install build prerequisites for [psycopg2](https://www.psycopg.org/docs/install.html#build-prerequisites):

- A C compiler
- The Python header files. They are usually installed in a package such as `python-dev` or `python3-dev`.
- `libpq` and `pg_config`
  - The `libpq` header files. They are usually installed in a package such as `libpq-dev`.
  - The `pg_config` program: it is usually installed by the `libpq-dev` package but sometimes it is not in a `PATH` directory.
  - On macOS, can be installed via `brew install libpq`. Make sure the installation path is added to your PATH, otherwise `pg_config` will not be available.
  - On Fedora, it can be installed with `dnf install libpq-devel`

Note:
In macOS with M1/M2 `pip` will fail to install in a virtualenvironment unless LDFLAGS reference the openssl library path. It can be fixed with `export LDFLAGS="-I/opt/homebrew/opt/openssl/include -L/opt/homebrew/opt/openssl/lib"`.

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
You may also need to first [install a rust compiler](https://www.rust-lang.org/tools/install) ([Mac OS directions](https://sourabhbajaj.com/mac-setup/Rust/)) and then run `python3 -m pip install --upgrade pip setuptools_rust`.

Install runtime requirements:

Versions can be found in [qontract-reconcile-base Dockerfile](https://github.com/app-sre/container-images/blob/master/qontract-reconcile-base/Dockerfile).

- amtool
- git-secrets
- helm
- kubectl
- oc
- promtool
- skopeo
- terraform

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

For more flexible way to run in container, please see [qontract-development-cli](https://github.com/app-sre/qontract-development-cli).

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

## Query Classes

We use [qenerate](https://github.com/app-sre/qenerate) to generate data classes for GQL queries.
GQL definitions and generated classes can be found [here](reconcile/gql_definitions/).

### Workflow

1. Define your query or fragment in a `.gql` file somewhere in `reconcile/gql_definitions`.
2. Every gql file must hold exactly one `query` OR `fragment` definition. You must not have multiple definitions within one file.
3. Do not forget to add `# qenerate: plugin=pydantic_v1` in the beginning of the file. This tells `qenerate` which plugin is used to render the code.
4. Have an up-to-date schema available at localhost:4000
5. `make gql-introspection` gets the type definitions. They will be stored in `reconcile/gql_definitions/introspection.json`
6. `make gql-query-classes` generates the data classes for your queries and fragments

## Troubleshooting

`faulthandler` is enabled for this project and SIGUSR1 is registered to dump the traceback. To do so, you can use `kill -USR1 pid` where pid is the ID of the qontract-reconcile process.

## Code style guide

Qontract-reconcile uses [PEP8](https://peps.python.org/pep-0008/) as the code style guide.
The style is enforced via [PR checks](#ci-tooling) with the help of the following utilities:

- [Ruff - An extremely fast Python linter and code formatter, written in Rust.](https://docs.astral.sh/ruff/)
- [Mypy](https://mypy.readthedocs.io/en/stable/)

Run `make format` before you commit your changes to keep the code compliant.

## Release

Release version are calculated from git tags of the form X.Y.Z.

- If the current commit has such a tag, it will be used as is
- Otherwise the latest tag of that format is used and:
  - the patch label (Z) is incremented
  - the string `.pre<count>+<commitid>` is appended. `<count>` is the number of commits since the X.Y.Z tag. `<commitid> is... the current commitid.

After the PR is merged, a CI job will be triggered that will publish the package to pypi: <https://pypi.org/project/qontract-reconcile>.

## Licence

[Apache License Version 2.0](LICENSE).

## Authors

These tools have been written by the [Red Hat App-SRE Team](mailto:sd-app-sre@redhat.com).
