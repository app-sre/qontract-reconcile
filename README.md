![](https://img.shields.io/github/license/app-sre/qontract-reconcile.svg?style=flat)

# qontract-reconcile

A tool to reconcile services with their desired state as defined in App-Interface.
In addition, e2e tests are available to detect potential problems reconciling services with their desired state.

## Subcommands

### qontract-reconcile

- `aws-garbage-collector`: Delete orphan AWS resources.
- `aws-iam-keys`: Delete IAM access keys by access key ID.
- `github`: Configures the teams and members in a GitHub org.
- `github-repo-invites`: Accept GitHub repository invitations for known repositories.
- `github-users`: Validate compliance of GitHub user profiles.
- `gitlab-housekeeping`: Manage issues and merge requests on GitLab projects.
- `gitlab-members` : Manage GitLab group members.
- `gitlab-permissions`: Manage permissions on GitLab projects.
- `jenkins-job-builder`: Manage Jenkins jobs configurations using jenkins-jobs
- `jenkins-plugins`: Manage Jenkins plugins installation via REST API.
- `jenkins-roles`: Manage Jenkins roles association via REST API.
- `jenkins-webhooks`: Manage web hooks to Jenkins jobs.
- `ldap-users`: Removes users which are not found in LDAP search.
- `openshift-groups`: Manages OpenShift Groups.
- `openshift-namespaces`: Manages OpenShift Namespaces.
- `openshift-resources`: Manages OpenShift Resources.
- `openshift-resources-annotate`: Annotates OpenShift Resources so they can be used by the `openshift-resources` integration.
- `openshift-rolebinding`: Configures Rolebindings in OpenShift clusters.
- `openshift-users`: Deletion of users from OpenShift clusters.
- `quay-membership`: Configures the teams and members in Quay.
- `quay-repos`: Creates and Manages Quay Repos.
- `slack-usergroups`: Manage Slack User Groups (channels and users).
- `terraform-resources`: Manage AWS Resources using Terraform.
- `terraform-users`: Manage AWS users using Terraform.

### e2e-tests

- `create-namespace`: A test to create a namespace and verify that required `RoleBinding`s are created as well to be able to reconcile them.
- `dedicated-admin-rolebindings`: A test to verify that all required namespaces have the required `RoleBinding`s to be able to reconcile them.

## Usage

Use [config.toml.example](config.toml.example) as a template to create a `config.toml` file.

Run a reconcile integration like this:

```sh
qontract-reconcile --config config.toml --dry-run <subcommand>

# review output and run without `--dry-run` to perform actual changes
qontract-reconcile --config config.toml <subcommand>
```

## Installation

Create and enter the [virtualenv](https://virtualenv.pypa.io/en/latest/) environment:

```sh
virtualenv venv
source venv/bin/activate

# make sure you are running the latest setuptools
pip install --upgrade pip setuptools
```

Install the package:

```sh
python setup.py install

# or alternatively use this for a devel environment
python setup.py develop
```

### Requirements

Please see [setup.py](setup.py).

## Licence

[Apache License Version 2.0](LICENSE).

## Authors

These tools have been written by the [Red Hat App-SRE Team](sd-app-sre@redhat.com).
