import sys
from textwrap import indent
from typing import (
    Any,
    Optional,
)

from reconcile import (
    queries,
    typed_queries,
)
from reconcile.utils import (
    expiration,
    gql,
)
from reconcile.utils.aws_api import AWSApi
from reconcile.utils.secret_reader import SecretReader
from reconcile.utils.semver_helper import make_semver
from reconcile.utils.smtp_client import (
    DEFAULT_SMTP_TIMEOUT,
    SmtpClient,
    get_smtp_server_connection,
)
from reconcile.utils.terraform_client import TerraformClient as Terraform
from reconcile.utils.terrascript_aws_client import TerrascriptClient as Terrascript

TF_POLICY = """
name
mandatory
policy
account {
  name
  uid
}
"""

TF_QUERY = """
{
  roles: roles_v1 {
    name
    users {
      org_username
      aws_username
      public_gpg_key
    }
    aws_groups {
      name
      policies
      account {
        name
        consoleUrl
        uid
        policies {
          %s
        }
      }
    }
    user_policies {
      %s
    }
    expirationDate
  }
}
""" % (
    indent(TF_POLICY, 10 * " "),
    indent(TF_POLICY, 6 * " "),
)

QONTRACT_INTEGRATION = "terraform_users"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 4, 2)
QONTRACT_TF_PREFIX = "qrtf"


def get_tf_roles() -> list[dict[str, Any]]:
    gqlapi = gql.get_api()
    roles: list[dict] = expiration.filter(gqlapi.query(TF_QUERY)["roles"])
    return [
        r
        for r in roles
        if r["aws_groups"] is not None or r["user_policies"] is not None
    ]


def setup(
    print_to_file, thread_pool_size: int, account_name: Optional[str] = None
) -> tuple[list[dict[str, Any]], dict[str, str], bool, AWSApi]:
    accounts = queries.get_aws_accounts(terraform_state=True)
    if account_name:
        accounts = [n for n in accounts if n["name"] == account_name]
        if not accounts:
            raise ValueError(f"aws account {account_name} is not found")
    settings = queries.get_app_interface_settings()
    ts = Terrascript(
        QONTRACT_INTEGRATION,
        QONTRACT_TF_PREFIX,
        thread_pool_size,
        accounts,
        settings=settings,
    )
    err = ts.populate_users(get_tf_roles())
    working_dirs = ts.dump(print_to_file)
    aws_api = AWSApi(1, accounts, settings=settings, init_users=False)

    return accounts, working_dirs, err, aws_api


def send_email_invites(new_users, smtp_client: SmtpClient):
    msg_template = """
You have been invited to join the {} AWS account!
Below you will find credentials for the first sign in.
You will be requested to change your password.

The password is encrypted with your public gpg key. To decrypt the password:

echo <password> | base64 -d | gpg -d - && echo
(you will be asked to provide your passphrase to unlock the secret)

Once you are logged in, navigate to the "Security credentials" page [1] and enable MFA [2].
Once you have enabled MFA, sign out and sign in again.

Details:

Console URL: {}
Username: {}
Encrypted password: {}

[1] https://console.aws.amazon.com/iam/home#security_credential
[2] https://docs.aws.amazon.com/IAM/latest/UserGuide/id_credentials_mfa.html

"""
    mails = []
    for account, console_url, user_name, enc_password in new_users:
        to = user_name
        subject = "Invitation to join the {} AWS account".format(account)
        body = msg_template.format(account, console_url, user_name, enc_password)
        mails.append((to, subject, body))
    smtp_client.send_mails(mails)


def cleanup_and_exit(tf=None, status=False):
    if tf is not None:
        tf.cleanup()
    sys.exit(status)


def run(
    dry_run: bool,
    print_to_file: Optional[str] = None,
    enable_deletion: bool = False,
    thread_pool_size: int = 10,
    send_mails: bool = True,
    account_name: Optional[str] = None,
):
    # setup errors should skip resources that will lead
    # to terraform errors. we should still do our best
    # to reconcile all valid resources for all accounts.
    accounts, working_dirs, setup_err, aws_api = setup(
        print_to_file, thread_pool_size, account_name
    )

    if print_to_file:
        cleanup_and_exit()
    if not working_dirs:
        err = True
        cleanup_and_exit(status=err)

    tf = Terraform(
        QONTRACT_INTEGRATION,
        QONTRACT_INTEGRATION_VERSION,
        QONTRACT_TF_PREFIX,
        accounts,
        working_dirs,
        thread_pool_size,
        aws_api,
        init_users=True,
    )
    if tf is None:
        err = True
        cleanup_and_exit(tf, err)

    disabled_deletions_detected, err = tf.plan(enable_deletion)
    if err:
        cleanup_and_exit(tf, err)
    if disabled_deletions_detected:
        cleanup_and_exit(tf, disabled_deletions_detected)

    if dry_run:
        cleanup_and_exit(tf, setup_err)

    err = tf.apply()
    if err:
        cleanup_and_exit(tf, err)

    if send_mails:
        new_users = tf.get_new_users()
        smtp_settings = typed_queries.smtp.settings()
        smtp_client = SmtpClient(
            server=get_smtp_server_connection(
                secret_reader=SecretReader(
                    settings=queries.get_secret_reader_settings()
                ),
                secret=smtp_settings.credentials,
            ),
            mail_address=smtp_settings.mail_address,
            timeout=smtp_settings.timeout or DEFAULT_SMTP_TIMEOUT,
        )
        send_email_invites(new_users, smtp_client)

    cleanup_and_exit(tf, setup_err)


def early_exit_desired_state(*args, **kwargs) -> dict[str, Any]:
    return {
        "accounts": queries.get_aws_accounts(terraform_state=True),
        "roles": get_tf_roles(),
    }
