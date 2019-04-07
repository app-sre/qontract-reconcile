import sys
import semver

import utils.gql as gql
import reconcile.openshift_resources as openshift_resources

from utils.terrascript_client import TerrascriptClient as Terrascript
from utils.terraform_client import OR, TerraformClient as Terraform
from utils.openshift_resource import ResourceInventory

TF_QUERY = """
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
        overrides
      }
      ... on NamespaceTerraformResourceS3_v1 {
        account
        identifier
        defaults
        overrides
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
    }
  }
}
"""

QONTRACT_INTEGRATION = 'terraform_resources'
QONTRACT_INTEGRATION_VERSION = semver.format_version(0, 1, 1)
QONTRACT_TF_PREFIX = 'qrtf'


def adjust_tf_query(tf_query):
    out_tf_query = []
    for namespace_info in tf_query:
        managed_terraform_resources = \
          namespace_info.get('managedTerraformResources')
        if not managed_terraform_resources:
            continue
        # adjust to match openshift_resources functions
        namespace_info['managedResourceTypes'] = ['Secret']
        out_tf_query.append(namespace_info)
    return out_tf_query


def get_tf_query():
    gqlapi = gql.get_api()
    tf_query = gqlapi.query(TF_QUERY)['namespaces']
    return adjust_tf_query(tf_query)


def populate_oc_resources(spec, ri):
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


def fetch_current_state(tf_query):
    ri = ResourceInventory()
    oc_map = {}
    state_specs = \
        openshift_resources.init_specs_to_fetch(ri, oc_map, tf_query)
    for spec in state_specs:
        populate_oc_resources(spec, ri)
    return ri, oc_map


def setup(print_only):
    tf_query = get_tf_query()
    ri, oc_map = fetch_current_state(tf_query)
    ts = Terrascript(QONTRACT_INTEGRATION,
                     QONTRACT_TF_PREFIX,
                     oc_map)
    ts.populate(tf_query)
    working_dirs = ts.dump(print_only)

    return ri, oc_map, working_dirs


def cleanup_and_exit(tf=None, status=False):
    if tf is not None:
        tf.cleanup()
    sys.exit(status)


def run(dry_run=False, print_only=False, enable_deletion=False):
    ri, oc_map, working_dirs = setup(print_only)
    if print_only:
        cleanup_and_exit()

    tf = Terraform(QONTRACT_INTEGRATION,
                   QONTRACT_INTEGRATION_VERSION,
                   QONTRACT_TF_PREFIX,
                   working_dirs)
    if tf is None:
        err = True
        cleanup_and_exit(tf, err)

    deletions_detected, err = tf.plan(enable_deletion)
    if err:
        cleanup_and_exit(tf, err)
    if deletions_detected and not enable_deletion:
        cleanup_and_exit(tf, deletions_detected)

    if dry_run:
        cleanup_and_exit(tf)

    err = tf.apply()
    if err:
        cleanup_and_exit(tf, err)

    tf.populate_desired_state(ri)
    openshift_resources.realize_data(dry_run, oc_map, ri)

    cleanup_and_exit(tf)
