import sys
import semver

import utils.gql as gql
import utils.smtp_client as smtp_client

from utils.terrascript_client import TerrascriptClient as Terrascript
from utils.terraform_client import TerraformClient as Terraform

TF_QUERY = """
{
  roles: roles_v1 {
    users {
      redhat_username
      public_gpg_key
    }
    aws_groups {
      name
      policies
      account {
        name
        consoleUrl
      }
    }
    user_policies {
      name
      policy
      account {
        name
      }
    }
  }
}
"""

QONTRACT_INTEGRATION = 'terraform_users'
QONTRACT_INTEGRATION_VERSION = semver.format_version(0, 4, 1)
QONTRACT_TF_PREFIX = 'qrtf'


def adjust_tf_query(tf_query):
    return [r for r in tf_query if r['aws_groups'] is not None]


def get_tf_query():
    gqlapi = gql.get_api()
    tf_query = gqlapi.query(TF_QUERY)['roles']
    return adjust_tf_query(tf_query)


def setup(print_only, thread_pool_size):
    tf_query = get_tf_query()
    ts = Terrascript(QONTRACT_INTEGRATION,
                     QONTRACT_TF_PREFIX,
                     thread_pool_size)
    err = ts.populate_users(tf_query)
    if err:
        return None, err

    working_dirs = ts.dump(print_only)

    return working_dirs, None


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
        enable_deletion=False, io_dir='throughput/',
        thread_pool_size=10, send_mails=True):
    working_dirs, err = setup(print_only, thread_pool_size)
    if err:
        cleanup_and_exit(status=err)
    if print_only:
        cleanup_and_exit()

    tf = Terraform(QONTRACT_INTEGRATION,
                   QONTRACT_INTEGRATION_VERSION,
                   QONTRACT_TF_PREFIX,
                   working_dirs,
                   thread_pool_size,
                   init_users=True)
    if tf is None:
        err = True
        cleanup_and_exit(tf, err)

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

    err = tf.apply()
    if err:
        cleanup_and_exit(tf, err)

    if send_mails:
        new_users = tf.get_new_users()
        send_email_invites(new_users)

    cleanup_and_exit(tf)
