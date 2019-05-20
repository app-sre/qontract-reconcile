![](https://img.shields.io/github/license/app-sre/qontract-reconcile.svg?style=flat)

# qontract-reconcile

Tool to reconcile services with their desired state as defined in the app-interface DB.

## Subcommands

- `qontract-reconcile github`: Configures the teams and members in a GitHub org.
- `qontract-reconcile quay-membership`: Configures the teams and members in Quay.
- `qontract-reconcile openshift-rolebinding`: Configures Rolebindings in OpenShift clusters.
- `qontract-reconcile openshift-groups`: Manages OpenShift Groups.
- `qontract-reconcile openshift-resources`: Manages OpenShift Resources.
- `qontract-reconcile openshift-namespaces`: Manages OpenShift Namespaces.
- `qontract-reconcile openshift-resources-annotate`: Annotates OpenShift Resources so they can be used by the `openshift-resources` integration.
- `qontract-reconcile quay-repos`: Creates and Manages Quay Repos.
- `qontract-reconcile ldap-users`: Removes users which are not found in LDAP search.
- `qontract-reconcile terraform-resources`: Manage AWS Resources using Terraform.

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
