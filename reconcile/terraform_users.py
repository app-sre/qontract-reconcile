import sys

import reconcile.utils.gql as gql
from reconcile.utils.smtp_client import SmtpClient
import reconcile.queries as queries

from reconcile.utils.semver_helper import make_semver
from reconcile.utils.terrascript_client import TerrascriptClient as Terrascript
from reconcile.utils.terraform_client import TerraformClient as Terraform

TF_QUERY = """
{
  roles: roles_v1 {
    users {
      org_username
      public_gpg_key
    }
    aws_groups {
      name
      policies
      account {
        name
        consoleUrl
        uid
      }
    }
    user_policies {
      name
      policy
      account {
        name
        uid
      }
    }
  }
}
"""

QONTRACT_INTEGRATION = 'terraform_users'
QONTRACT_INTEGRATION_VERSION = make_semver(0, 4, 2)
QONTRACT_TF_PREFIX = 'qrtf'


def setup(print_only, thread_pool_size):
    gqlapi = gql.get_api()
    accounts = queries.get_aws_accounts()
    settings = queries.get_app_interface_settings()
    roles = gqlapi.query(TF_QUERY)['roles']
    tf_roles = [r for r in roles
                if r['aws_groups'] is not None
                or r['user_policies'] is not None]
    ts = Terrascript(QONTRACT_INTEGRATION,
                     QONTRACT_TF_PREFIX,
                     thread_pool_size,
                     accounts,
                     settings=settings)
    err = ts.populate_users(tf_roles)
    if err:
        return None

    working_dirs = ts.dump(print_only)

    return accounts, working_dirs


def send_email_invites(new_users, settings):
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
    smtp_client = SmtpClient(settings=settings)
    smtp_client.send_mails(mails)


def cleanup_and_exit(tf=None, status=False):
    if tf is not None:
        tf.cleanup()
    sys.exit(status)


def run(dry_run, print_only=False,
        enable_deletion=False, io_dir='throughput/',
        thread_pool_size=10, send_mails=True):
    accounts, working_dirs = setup(print_only, thread_pool_size)
    if print_only:
        cleanup_and_exit()
    if working_dirs is None:
        err = True
        cleanup_and_exit(status=err)

    tf = Terraform(QONTRACT_INTEGRATION,
                   QONTRACT_INTEGRATION_VERSION,
                   QONTRACT_TF_PREFIX,
                   accounts,
                   working_dirs,
                   thread_pool_size,
                   init_users=True)
    if tf is None:
        err = True
        cleanup_and_exit(tf, err)

    disabled_deletions_detected, err = tf.plan(enable_deletion)
    if err:
        cleanup_and_exit(tf, err)
    tf.dump_deleted_users(io_dir)
    if disabled_deletions_detected:
        cleanup_and_exit(tf, disabled_deletions_detected)

    if dry_run:
        cleanup_and_exit(tf)

    err = tf.apply()
    if err:
        cleanup_and_exit(tf, err)

    if send_mails:
        new_users = tf.get_new_users()
        settings = queries.get_app_interface_settings()
        send_email_invites(new_users, settings)

    cleanup_and_exit(tf)
