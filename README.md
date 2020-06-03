![](https://img.shields.io/github/license/app-sre/qontract-reconcile.svg?style=flat)

# qontract-reconcile

A tool to reconcile services with their desired state as defined in App-Interface.
In addition, e2e tests are available to detect potential problems reconciling services with their desired state.
Additional tools that use the libraries created by the reconciliations are also hosted here.

## Subcommands

### qontract-reconcile

- `aws-garbage-collector`: Delete orphan AWS resources.
- `aws-iam-keys`: Delete IAM access keys by access key ID.
- `aws-ecr-image-pull-secrets`: Generate AWS ECR image pull secrets and store them in Vault.
- `aws-support-cases-sos`: Scan AWS support cases for reports of leaked keys and remove them (only submits PR)
- `github-repo-invites`: Accept GitHub repository invitations for known repositories.
- `github-scanner`: Scan GitHub repositories for leaked keys and remove them (only submits PR).
- `github-users`: Validate compliance of GitHub user profiles.
- `github`: Configures the teams and members in a GitHub org.
- `github-owners`: Configures owners in a GitHub org.
- `github-validator`: Validates GitHub organization settings.
- `gitlab-fork-compliance`: Ensures that forks of App Interface are compliant.
- `gitlab-housekeeping`: Manage issues and merge requests on GitLab projects.
- `gitlab-integrations`: Manage integrations on GitLab projects.
- `gitlab-members` : Manage GitLab group members.
- `gitlab-owners`: Adds an `approved` label on gitlab merge requests based on OWNERS files schema.
- `gitlab-permissions`: Manage permissions on GitLab projects.
- `gitlab-projects`: Create GitLab projects.
- `jenkins-job-builder`: Manage Jenkins jobs configurations using jenkins-jobs
- `jenkins-plugins`: Manage Jenkins plugins installation via REST API.
- `jenkins-roles`: Manage Jenkins roles association via REST API.
- `jenkins-webhooks`: Manage web hooks to Jenkins jobs.
- `jenkins-webhooks-cleaner`: Remove webhooks to previous Jenkins instances.
- `jira-watcher`: Watch for changes in Jira boards and notify on Slack.
- `ldap-users`: Removes users which are not found in LDAP search.
- `openshift-acme`: Manages openshift-acme deployments (https://github.com/tnozicka/openshift-acme)
- `openshift-clusterrolebindings`: Configures ClusterRolebindings in OpenShift clusters.
- `openshift-groups`: Manages OpenShift Groups.
- `openshift-limitranges`: Manages OpenShift LimitRange objects.
- `openshift-resourcequotas`: Manages OpenShift ResourceQuota objects.
- `openshift-namespaces`: Manages OpenShift Namespaces.
- `openshift-network-policies`: Manages OpenShift NetworkPolicies.
- `openshift-performance-parameters`: Manages Performance Parameters files from services.
- `openshift-resources`: Manages OpenShift Resources.
- `openshift-rolebindings`: Configures Rolebindings in OpenShift clusters.
- `openshift-routes`: Manages OpenShift Routes.
- `openshift-saas-deploy`: Manage OpenShift resources defined in Saas files (SaasHerder).
- `openshift-saas-deploy-trigger-moving-commits`: Trigger jobs in Jenkins when a commit changed for a ref.
- `openshift-saas-deploy-trigger-configs`: Trigger jobs in Jenkins when configuration changed.
- `openshift-serviceaccount-tokens`: Use OpenShift ServiceAccount tokens across namespaces/clusters.
- `openshift-users`: Deletion of users from OpenShift clusters.
- `openshift-vault-secrets`: Manages OpenShift Secrets from Vault.
- `quay-membership`: Configures the teams and members in Quay.
- `quay-mirror`: Mirrors external images into Quay.
- `quay-repos`: Creates and Manages Quay Repos.
- `slack-usergroups`: Manage Slack User Groups (channels and users).
- `sql-query`: Runs SQL Queries against app-interface RDS resources.
- `terraform-resources`: Manage AWS Resources using Terraform.
- `terraform-users`: Manage AWS users using Terraform.
- `terraform-vpc-peerings`: Manage VPC peerings between OSDv4 clusters and AWS accounts.
- `ocm-groups`: Manage membership in OpenShift groups using OpenShift Cluster Manager.
- `ocm-clusters`: Manages (currently: validates only) clusters desired state with current state in OCM.
- `ocm-aws-infrastructure-access`: Grants AWS infrastructure access to members in AWS groups via OCM.
- `email-sender`: Send email notifications to app-interface audience.
- `requests-sender`: Send emails to users based on requests submitted to app-interface.
- `service-dependencies`: Validate dependencies are defined for each service.
- `sentry-config`: Configure and enforce sentry instance configuration.
- `saas-file-owners`: Adds an `approved` label on merge requests based on approver schema for saas files.
- `user-validator`: Validate user files.

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

## OpenShift usage

OpenShift templates can be found [here](/openshift/qontract-reconcile.yaml). In order to add integrations there please use the [helm](/helm/README.md) chart provided.

## Installation

Create and enter the [virtualenv](https://virtualenv.pypa.io/en/latest/) environment:

```sh
python3 -m venv venv
source venv/bin/activate

# make sure you are running the latest setuptools
python3 -m pip install --upgrade pip setuptools
```

Install the package:

```sh
python3 setup.py install

# or alternatively use this for a devel environment
python3 setup.py develop
```

### Requirements

Please see [setup.py](setup.py).

## Licence

[Apache License Version 2.0](LICENSE).

## Authors

These tools have been written by the [Red Hat App-SRE Team](sd-app-sre@redhat.com).
