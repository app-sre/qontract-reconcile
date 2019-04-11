import sys
import semver

import utils.gql as gql
import reconcile.openshift_resources as openshift_resources
import utils.smtp_client as smtp_client

from utils.terrascript_client import TerrascriptClient as Terrascript
from utils.terraform_client import OR, TerraformClient as Terraform
from utils.openshift_resource import ResourceInventory

from multiprocessing.dummy import Pool as ThreadPool
from functools import partial

TF_RESOURCES_QUERY = """
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

TF_IAM_QUERY = """
{
  roles: roles_v1 {
    users {
      redhat_username
      public_gpg_key
    }
    aws_groups {
      ...on AWSGroup_v1 {
        name
        policies
        account {
          name
          consoleUrl
        }
      }
    }
  }
}
"""

QONTRACT_INTEGRATION = 'terraform_resources'
QONTRACT_INTEGRATION_VERSION = semver.format_version(0, 2, 0)
QONTRACT_TF_PREFIX = 'qrtf'


def adjust_tf_resources_query(tf_query):
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


def get_tf_resources_query():
    gqlapi = gql.get_api()
    tf_query = gqlapi.query(TF_RESOURCES_QUERY)['namespaces']
    return adjust_tf_resources_query(tf_query)


def adjust_tf_iam_query(tf_query):
    return [r for r in tf_query if r['aws_groups'] is not None]


def get_tf_iam_query():
    gqlapi = gql.get_api()
    tf_query = gqlapi.query(TF_IAM_QUERY)['roles']
    return adjust_tf_iam_query(tf_query)


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


def fetch_current_state(tf_query, thread_pool_size):
    ri = ResourceInventory()
    oc_map = {}
    state_specs = \
        openshift_resources.init_specs_to_fetch(ri, oc_map, tf_query)

    pool = ThreadPool(thread_pool_size)
    populate_oc_resources_partial = \
        partial(populate_oc_resources, ri=ri)
    pool.map(populate_oc_resources_partial, state_specs)

    return ri, oc_map


def setup(print_only, thread_pool_size):
    tf_iam_query = get_tf_iam_query()
    tf_resources_query = get_tf_resources_query()
    ri, oc_map = fetch_current_state(tf_resources_query, thread_pool_size)
    ts = Terrascript(QONTRACT_INTEGRATION,
                     QONTRACT_TF_PREFIX,
                     oc_map,
                     thread_pool_size)
    ts.populate_iam(tf_iam_query)
    ts.populate_resources(tf_resources_query)
    working_dirs = ts.dump(print_only)

    return ri, oc_map, working_dirs


def send_email_invites(new_users):
    msg_template = '''
You have been invited to join the {} AWS account!
Below you will find credentials for the first sign in.
You will be requested to change your password.

The password is encrypted with your public gpg key. To decrypt the password:

echo <password> | base64 -d | gpg -d - && echo
(you will be asked to provide your passphrase to unlock the secret)

Details:

Console URL: {}
Username: {}
Encrypted password: {}

'''
    mails = []
    for account, console_url, user_name, enc_password in new_users:
        to = user_name
        subject = 'Invitation to join the {} AWS account'.format(account)
        body = msg_template.format(account, console_url,
                                   user_name, enc_password)
        mails.append((to, subject, body))

    smtp_client.send_mails(mails)


def cleanup_and_exit(tf=None, status=False):
    if tf is not None:
        tf.cleanup()
    sys.exit(status)


def run(dry_run=False, print_only=False,
        enable_deletion=False, thread_pool_size=10):
    ri, oc_map, working_dirs = setup(print_only, thread_pool_size)
    if print_only:
        cleanup_and_exit()

    tf = Terraform(QONTRACT_INTEGRATION,
                   QONTRACT_INTEGRATION_VERSION,
                   QONTRACT_TF_PREFIX,
                   working_dirs,
                   thread_pool_size)
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

    new_users = tf.get_new_users()
    send_email_invites(new_users)

    cleanup_and_exit(tf)
