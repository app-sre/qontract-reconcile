import sys
import shutil
import semver
import logging

import reconcile.utils.gql as gql
import reconcile.utils.threaded as threaded
from reconcile.utils.vault import VaultClient
import reconcile.openshift_base as ob
import reconcile.queries as queries

from reconcile.utils.terrascript_client import TerrascriptClient as Terrascript
from reconcile.utils.terraform_client import OR, TerraformClient as Terraform
from reconcile.utils.openshift_resource import ResourceInventory
from reconcile.utils.oc import OC_Map
from reconcile.utils.defer import defer
from reconcile.aws_iam_keys import run as disable_keys
from reconcile.utils.oc import StatusCodeError

from textwrap import indent


TF_RESOURCE = """
provider
... on NamespaceTerraformResourceRDS_v1 {
  account
  identifier
  defaults
  availability_zone
  parameter_group
  overrides
  output_resource_name
  enhanced_monitoring
  replica_source
  output_resource_db_name
  reset_password
}
... on NamespaceTerraformResourceS3_v1 {
  account
  region
  identifier
  defaults
  overrides
  sqs_identifier
  s3_events
  bucket_policy
  output_resource_name
  storage_class
}
... on NamespaceTerraformResourceElastiCache_v1 {
  account
  identifier
  defaults
  parameter_group
  region
  overrides
  output_resource_name
}
... on NamespaceTerraformResourceServiceAccount_v1 {
  account
  identifier
  variables
  policies
  user_policy
  output_resource_name
}
... on NamespaceTerraformResourceSQS_v1 {
  account
  region
  identifier
  output_resource_name
  specs {
    defaults
    queues {
      key
      value
    }
  }
}
... on NamespaceTerraformResourceDynamoDB_v1 {
  account
  region
  identifier
  output_resource_name
  specs {
    defaults
    tables {
      key
      value
    }
  }
}
... on NamespaceTerraformResourceECR_v1 {
  account
  identifier
  region
  output_resource_name
}
... on NamespaceTerraformResourceS3CloudFront_v1 {
  account
  region
  identifier
  defaults
  output_resource_name
  storage_class
}
... on NamespaceTerraformResourceS3SQS_v1 {
  account
  region
  identifier
  defaults
  output_resource_name
  storage_class
}
... on NamespaceTerraformResourceCloudWatch_v1 {
  account
  region
  identifier
  defaults
  es_identifier
  filter_pattern
  output_resource_name
}
... on NamespaceTerraformResourceKMS_v1 {
  account
  region
  identifier
  defaults
  overrides
  output_resource_name
}
... on NamespaceTerraformResourceElasticSearch_v1 {
  account
  region
  identifier
  defaults
  output_resource_name
}
... on NamespaceTerraformResourceACM_v1 {
  account
  region
  identifier
  secret {
    path
    field
  }
  output_resource_name
}
... on NamespaceTerraformResourceKinesis_v1 {
  account
  region
  identifier
  defaults
  output_resource_name
}
"""


TF_NAMESPACES_QUERY = """
{
  namespaces: namespaces_v1 {
    name
    managedTerraformResources
    terraformResources {
      %s
    }
    cluster {
      name
      serverUrl
      jumpHost {
        hostname
        knownHosts
        user
        port
        identity {
          path
          field
          format
        }
      }
      automationToken {
        path
        field
        format
      }
      internal
    }
  }
}
""" % (indent(TF_RESOURCE, 6*' '))

QONTRACT_INTEGRATION = 'terraform_resources'
QONTRACT_INTEGRATION_VERSION = semver.format_version(0, 5, 2)
QONTRACT_TF_PREFIX = 'qrtf'


def populate_oc_resources(spec, ri):
    if spec.oc is None:
        return

    logging.debug("[populate_oc_resources] cluster: " + spec.cluster
                  + " namespace: " + spec.namespace
                  + " resource: " + spec.resource)

    try:
        for item in spec.oc.get_items(spec.resource,
                                      namespace=spec.namespace):
            openshift_resource = OR(item,
                                    QONTRACT_INTEGRATION,
                                    QONTRACT_INTEGRATION_VERSION)
            ri.add_current(
                spec.cluster,
                spec.namespace,
                spec.resource,
                openshift_resource.name,
                openshift_resource
            )
    except StatusCodeError as e:
        ri.register_error()
        msg = 'cluster: {},'
        msg += 'namespace: {},'
        msg += 'resource: {},'
        msg += 'exception: {}'
        msg = msg.format(spec.cluster, spec.namespace, spec.resource, str(e))
        logging.error(msg)


def fetch_current_state(dry_run, namespaces, thread_pool_size,
                        internal, use_jump_host):
    ri = ResourceInventory()
    if dry_run:
        return ri, None
    settings = queries.get_app_interface_settings()
    oc_map = OC_Map(namespaces=namespaces, integration=QONTRACT_INTEGRATION,
                    settings=settings, internal=internal,
                    use_jump_host=use_jump_host,
                    thread_pool_size=thread_pool_size)
    state_specs = \
        ob.init_specs_to_fetch(
            ri,
            oc_map,
            namespaces=namespaces,
            override_managed_types=['Secret']
        )
    threaded.run(populate_oc_resources, state_specs, thread_pool_size, ri=ri)

    return ri, oc_map


def init_working_dirs(accounts, thread_pool_size,
                      oc_map=None, settings=None):
    ts = Terrascript(QONTRACT_INTEGRATION,
                     QONTRACT_TF_PREFIX,
                     thread_pool_size,
                     accounts,
                     oc_map,
                     settings=settings)
    working_dirs = ts.dump()
    return ts, working_dirs


def setup(dry_run, print_only, thread_pool_size, internal,
          use_jump_host, account_name):
    gqlapi = gql.get_api()
    accounts = queries.get_aws_accounts()
    if account_name:
        accounts = [n for n in accounts
                    if n['name'] == account_name]
        if not accounts:
            raise ValueError(f"aws account {account_name} is not found")
    settings = queries.get_app_interface_settings()
    namespaces = gqlapi.query(TF_NAMESPACES_QUERY)['namespaces']
    tf_namespaces = [namespace_info for namespace_info in namespaces
                     if namespace_info.get('managedTerraformResources')]
    ri, oc_map = fetch_current_state(dry_run, tf_namespaces, thread_pool_size,
                                     internal, use_jump_host)
    ts, working_dirs = init_working_dirs(accounts, thread_pool_size,
                                         oc_map=oc_map,
                                         settings=settings)
    tf = Terraform(QONTRACT_INTEGRATION,
                   QONTRACT_INTEGRATION_VERSION,
                   QONTRACT_TF_PREFIX,
                   working_dirs,
                   thread_pool_size)
    existing_secrets = tf.get_terraform_output_secrets()
    ts.populate_resources(tf_namespaces, existing_secrets, account_name)
    ts.dump(print_only, existing_dirs=working_dirs)

    return ri, oc_map, tf, tf_namespaces


def cleanup_and_exit(tf=None, status=False, working_dirs={}):
    if tf is None:
        for wd in working_dirs.values():
            shutil.rmtree(wd)
    else:
        tf.cleanup()
    sys.exit(status)


def write_outputs_to_vault(vault_path, ri):
    integration_name = QONTRACT_INTEGRATION.replace('_', '-')
    vault_client = VaultClient()
    for cluster, namespace, _, data in ri:
        for name, d_item in data['desired'].items():
            secret_path = \
                f"{vault_path}/{integration_name}/{cluster}/{namespace}/{name}"
            secret = {'path': secret_path, 'data': d_item.body['data']}
            vault_client.write(secret)


@defer
def run(dry_run, print_only=False,
        enable_deletion=False, io_dir='throughput/',
        thread_pool_size=10, internal=None, use_jump_host=True,
        light=False, vault_output_path='',
        account_name=None, defer=None):

    ri, oc_map, tf, tf_namespaces = \
        setup(dry_run, print_only, thread_pool_size, internal,
              use_jump_host, account_name)

    if not dry_run:
        defer(lambda: oc_map.cleanup())

    if print_only:
        cleanup_and_exit()
    if tf is None:
        err = True
        cleanup_and_exit(tf, err)

    if not light:
        deletions_detected, err = tf.plan(enable_deletion)
        if err:
            cleanup_and_exit(tf, err)
        if deletions_detected:
            if enable_deletion:
                tf.dump_deleted_users(io_dir)
            else:
                cleanup_and_exit(tf, deletions_detected)

    if dry_run:
        cleanup_and_exit(tf)

    if not light:
        err = tf.apply()
        if err:
            cleanup_and_exit(tf, err)

    # Temporary skip apply secret for running tf-r per account locally.
    # The integration running on the cluster will manage the secret
    # after any manual running.
    # Will refactor with caller for further operator implement.
    if account_name:
        cleanup_and_exit(tf)

    tf.populate_desired_state(ri, oc_map, tf_namespaces)

    # temporarily not allowing resources to be deleted
    # or for pods to be recycled
    # this should be removed after we gained confidence
    # following the terraform 0.13 upgrade
    ob.realize_data(dry_run, oc_map, ri)

    disable_keys(dry_run, thread_pool_size,
                 disable_service_account_keys=True)

    if vault_output_path:
        write_outputs_to_vault(vault_output_path, ri)

    if ri.has_error_registered():
        err = True
        cleanup_and_exit(tf, err)

    cleanup_and_exit(tf)
