import sys
import shutil
import semver
import logging

import utils.gql as gql
import utils.threaded as threaded
import utils.vault_client as vault_client
import reconcile.openshift_base as ob
import reconcile.queries as queries

from utils.terrascript_client import TerrascriptClient as Terrascript
from utils.terraform_client import OR, TerraformClient as Terraform
from utils.openshift_resource import ResourceInventory
from utils.oc import OC_Map
from utils.defer import defer
from reconcile.aws_iam_keys import run as disable_keys
from utils.oc import StatusCodeError

TF_NAMESPACES_QUERY = """
{
  namespaces: namespaces_v1 {
    name
    managedTerraformResources
    terraformResources {
      provider
      ... on NamespaceTerraformResourceRDS_v1 {
        account
        identifier
        defaults
        parameter_group
        overrides
        output_resource_name
      }
      ... on NamespaceTerraformResourceS3_v1 {
        account
        region
        identifier
        defaults
        overrides
        output_resource_name
      }
      ... on NamespaceTerraformResourceElastiCache_v1 {
        account
        identifier
        defaults
        parameter_group
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
        output_resource_name
      }
      ... on NamespaceTerraformResourceS3CloudFront_v1 {
        account
        region
        identifier
        defaults
        output_resource_name
      }
    }
    cluster {
      name
      serverUrl
      automationToken {
        path
        field
        format
      }
      internal
    }
  }
}
"""

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
        msg = 'cluster: {},'
        msg += 'namespace: {},'
        msg += 'resource: {},'
        msg += 'exception: {}'
        msg = msg.format(spec.cluster, spec.namespace, spec.resource, str(e))
        logging.error(msg)


def fetch_current_state(namespaces, thread_pool_size, internal):
    ri = ResourceInventory()
    settings = queries.get_app_interface_settings()
    oc_map = OC_Map(namespaces=namespaces, integration=QONTRACT_INTEGRATION,
                    settings=settings, internal=internal)
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
                      print_only=False, oc_map=None, settings=None):
    ts = Terrascript(QONTRACT_INTEGRATION,
                     QONTRACT_TF_PREFIX,
                     thread_pool_size,
                     accounts,
                     oc_map,
                     settings=settings)
    working_dirs = ts.dump(print_only)
    return ts, working_dirs


def setup(print_only, thread_pool_size, internal):
    gqlapi = gql.get_api()
    accounts = queries.get_aws_accounts()
    settings = queries.get_app_interface_settings()
    namespaces = gqlapi.query(TF_NAMESPACES_QUERY)['namespaces']
    tf_namespaces = [namespace_info for namespace_info in namespaces
                     if namespace_info.get('managedTerraformResources')]
    ri, oc_map = fetch_current_state(tf_namespaces, thread_pool_size, internal)
    ts, working_dirs = init_working_dirs(accounts, thread_pool_size,
                                         print_only=print_only,
                                         oc_map=oc_map,
                                         settings=settings)
    tf = Terraform(QONTRACT_INTEGRATION,
                   QONTRACT_INTEGRATION_VERSION,
                   QONTRACT_TF_PREFIX,
                   working_dirs,
                   thread_pool_size)
    existing_secrets = tf.get_terraform_output_secrets()
    ts.populate_resources(tf_namespaces, existing_secrets)
    ts.dump(print_only, existing_dirs=working_dirs)

    return ri, oc_map, tf


def cleanup_and_exit(tf=None, status=False, working_dirs={}):
    if tf is None:
        for wd in working_dirs.values():
            shutil.rmtree(wd)
    else:
        tf.cleanup()
    sys.exit(status)


def write_outputs_to_vault(vault_path, ri):
    integration_name = QONTRACT_INTEGRATION.replace('_', '-')
    for cluster, namespace, _, data in ri:
        for name, d_item in data['desired'].items():
            secret_path = \
              f"{vault_path}/{integration_name}/{cluster}/{namespace}/{name}"
            secret = {'path': secret_path, 'data': d_item.body['data']}
            vault_client.write(secret)


@defer
def run(dry_run=False, print_only=False,
        enable_deletion=False, io_dir='throughput/',
        thread_pool_size=10, internal=None, light=False,
        vault_output_path='', defer=None):
    ri, oc_map, tf = setup(print_only, thread_pool_size, internal)
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

    tf.populate_desired_state(ri, oc_map)
    ob.realize_data(dry_run, oc_map, ri,
                    enable_deletion=enable_deletion)
    disable_keys(dry_run, thread_pool_size,
                 disable_service_account_keys=True)
    if vault_output_path:
        write_outputs_to_vault(vault_output_path, ri)

    cleanup_and_exit(tf)
