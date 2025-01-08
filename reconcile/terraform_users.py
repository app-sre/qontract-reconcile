import sys
from textwrap import indent
from typing import (
    Any,
    cast,
)

from reconcile import (
    queries,
    typed_queries,
)
from reconcile.change_owners.diff import IDENTIFIER_FIELD_NAME
from reconcile.gql_definitions.common.pgp_reencryption_settings import query
from reconcile.utils import (
    expiration,
    gql,
)
from reconcile.utils.aws_api import AWSApi
from reconcile.utils.disabled_integrations import integration_is_enabled
from reconcile.utils.runtime.integration import DesiredStateShardConfig
from reconcile.utils.secret_reader import SecretReader
from reconcile.utils.semver_helper import make_semver
from reconcile.utils.smtp_client import (
    DEFAULT_SMTP_TIMEOUT,
    SmtpClient,
    get_smtp_server_connection,
)
from reconcile.utils.terraform_client import TerraformClient as Terraform
from reconcile.utils.terrascript_aws_client import TerrascriptClient as Terrascript
from reconcile.utils.vault import (
    VaultClient,
    _VaultClient,
)

TF_POLICY = """
name
mandatory
policy
account {
  name
  sso
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
        sso
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


def _filter_participating_aws_accounts(
    accounts: list,
    roles: list[dict[str, Any]],
) -> list:
    participating_aws_account_names: set[str] = set()
    for role in roles:
        participating_aws_account_names.update(
            aws_group["account"]["name"] for aws_group in role["aws_groups"] or []
        )
        participating_aws_account_names.update(
            user_policy["account"]["name"]
            for user_policy in role["user_policies"] or []
        )
    return [a for a in accounts if a["name"] in participating_aws_account_names]


def setup(
    print_to_file,
    thread_pool_size: int,
    skip_reencrypt_accounts: list[str],
    appsre_pgp_key: str | None = None,
    account_name: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, str], bool, AWSApi]:
    accounts = [
        a
        for a in queries.get_aws_accounts(terraform_state=True)
        if integration_is_enabled(QONTRACT_INTEGRATION.replace("_", "-"), a)
        and (not account_name or a["name"] == account_name)
    ]
    roles = get_tf_roles()
    participating_aws_accounts = _filter_participating_aws_accounts(accounts, roles)

    settings = queries.get_app_interface_settings()
    ts = Terrascript(
        QONTRACT_INTEGRATION,
        QONTRACT_TF_PREFIX,
        thread_pool_size,
        participating_aws_accounts,
        settings=settings,
    )
    err = ts.populate_users(
        roles,
        skip_reencrypt_accounts,
        appsre_pgp_key=appsre_pgp_key,
    )
    working_dirs = ts.dump(print_to_file)
    aws_api = AWSApi(1, participating_aws_accounts, settings=settings, init_users=False)

    return participating_aws_accounts, working_dirs, err, aws_api


def send_email_invites(
    new_users,
    smtp_client: SmtpClient,
    skip_reencrypt_accounts: list[str],
):
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
        if account not in skip_reencrypt_accounts:
            continue
        to = user_name
        subject = f"Invitation to join the {account} AWS account"
        body = msg_template.format(account, console_url, user_name, enc_password)
        mails.append((to, subject, body))

    if len(mails) > 0:
        smtp_client.send_mails(mails)


def write_user_to_vault(
    vault_client: _VaultClient,
    vault_path: str,
    new_users: list[tuple[str, str, str, str]],
    skip_reencrypt_accounts: list[str],
):
    for account, console_url, user_name, enc_password in new_users:
        if account in skip_reencrypt_accounts:
            continue
        secret_path = f"{vault_path}/{account}_{user_name}"
        desired_secret = {
            "path": secret_path,
            "data": {
                "account": account,
                "user_name": user_name,
                "console_url": console_url,
                "encrypted_password": enc_password,
            },
        }
        vault_client.write(desired_secret, decode_base64=False)


def cleanup_and_exit(tf=None, status=False):
    if tf is not None:
        tf.cleanup()
    sys.exit(status)


def get_reencrypt_settings():
    all_reencrypt_settings = query(
        query_func=gql.get_api().query
    ).pgp_reencryption_settings

    skip_accounts: list[str] = []
    if not all_reencrypt_settings:
        reencrypt_settings = None
    elif len(all_reencrypt_settings) > 1:
        raise ValueError("Expecting only a single reencrypt settings entry")
    else:
        reencrypt_settings = all_reencrypt_settings[0]
        if reencrypt_settings.skip_aws_accounts:
            skip_accounts = [s.name for s in reencrypt_settings.skip_aws_accounts]

    appsre_pgp_key: str | None = None
    if reencrypt_settings is not None:
        appsre_pgp_key = reencrypt_settings.public_gpg_key

    return skip_accounts, appsre_pgp_key, reencrypt_settings


def run(
    dry_run: bool,
    print_to_file: str | None = None,
    enable_deletion: bool = False,
    thread_pool_size: int = 10,
    send_mails: bool = True,
    account_name: str | None = None,
):
    skip_accounts, appsre_pgp_key, reencrypt_settings = get_reencrypt_settings()

    # setup errors should skip resources that will lead
    # to terraform errors. we should still do our best
    # to reconcile all valid resources for all accounts.
    accounts, working_dirs, setup_err, aws_api = setup(
        print_to_file,
        thread_pool_size,
        skip_accounts,
        account_name=account_name,
        appsre_pgp_key=appsre_pgp_key,
    )

    if not accounts:
        # no enabled accounts found
        return

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

    new_users = tf.get_new_users()

    if reencrypt_settings:
        vc = cast(_VaultClient, VaultClient())
        write_user_to_vault(
            vc, reencrypt_settings.reencrypt_vault_path, new_users, skip_accounts
        )

    if send_mails:
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
        send_email_invites(new_users, smtp_client, skip_accounts)

    cleanup_and_exit(tf, setup_err)


def early_exit_desired_state(*args, **kwargs) -> dict[str, Any]:
    """
    Finding diffs in deeply nested structures is time/resource consuming.
    Having a unique known property to identify objects makes it easier to match
    the same object in different states. This speeds up the diffing process
    A LOT!

    The IDENTIFIER_FIELD_NAME is added for that purpose. It is a well known field
    for the DeepDiff library used in qontract-reconcile.
    """

    def add_account_identity(acc):
        acc[IDENTIFIER_FIELD_NAME] = acc["path"]
        return acc

    def add_role_identity(role):
        role[IDENTIFIER_FIELD_NAME] = role["name"]
        return role

    return {
        "accounts": [
            add_account_identity(a)
            for a in queries.get_aws_accounts(terraform_state=True)
            if integration_is_enabled(QONTRACT_INTEGRATION.replace("_", "-"), a)
        ],
        "roles": [add_role_identity(r) for r in get_tf_roles()],
    }


def desired_state_shard_config() -> DesiredStateShardConfig:
    return DesiredStateShardConfig(
        shard_arg_name="account_name",
        shard_path_selectors={
            "accounts[*].name",
            "roles[*].aws_groups[*].account.name",
            "roles[*].user_policies[*].account.name",
        },
        # Only run shard if less than 2 shards are affected. Else it is not worth the effort -> run everything.
        sharded_run_review=lambda proposal: len(proposal.proposed_shards) <= 2,
    )
