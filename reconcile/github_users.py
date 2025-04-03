import logging
import os
import re
from collections.abc import Callable

from github import Github
from github.GithubException import GithubException
from requests.exceptions import ReadTimeout
from sretoolbox.utils import (
    retry,
    threaded,
)

from reconcile import (
    mr_client_gateway,
    queries,
    typed_queries,
)
from reconcile.github_org import get_default_config
from reconcile.ldap_users import init_users as init_users_and_paths
from reconcile.utils.defer import defer
from reconcile.utils.mr import CreateDeleteUserAppInterface
from reconcile.utils.secret_reader import SecretReader
from reconcile.utils.smtp_client import (
    DEFAULT_SMTP_TIMEOUT,
    SmtpClient,
    get_smtp_server_connection,
)

GH_BASE_URL = os.environ.get("GITHUB_API", "https://api.github.com")

QONTRACT_INTEGRATION = "github-users"

UserAndCompany = tuple[str, str | None]


def init_github() -> Github:
    token = get_default_config()["token"]
    return Github(token, base_url=GH_BASE_URL)


@retry(exceptions=(GithubException, ReadTimeout))
def get_user_company(user: dict, github: Github) -> UserAndCompany:
    gh_user = github.get_user(login=user["github_username"])
    return user["org_username"], gh_user.company


def get_users_to_delete(results: list[UserAndCompany]) -> list[dict]:
    pattern = r"^.*[Rr]ed ?[Hh]at.*$"
    org_usernames_to_delete = [
        u for u, c in results if c is None or not re.search(pattern, c)
    ]
    users_and_paths = init_users_and_paths()
    return [u for u in users_and_paths if u["username"] in org_usernames_to_delete]


def send_email_notification(user: dict, smtp_client: SmtpClient) -> None:
    msg_template = """
Hello,

This is an automated message coming from App-Interface.

The App SRE team adheres to the OpenShift GitHub policy:
https://mojo.redhat.com/docs/DOC-1200784

Your GitHub profile does not comply with the following requirements:

- Company field should contain "Red Hat".


For any questions, please ping @app-sre-ic on #sd-app-sre in CoreOS Slack,
or mail us at sd-app-sre@redhat.com.

App-Interface repository: https://gitlab.cee.redhat.com/service/app-interface

"""
    to = user["username"]
    subject = "App-Interface compliance - GitHub profile"
    body = msg_template
    smtp_client.send_mail([to], subject, body)


@defer
def run(
    dry_run: bool,
    gitlab_project_id: str | None = None,
    thread_pool_size: int = 10,
    enable_deletion: bool = False,
    send_mails: bool = False,
    defer: Callable | None = None,
) -> None:
    smtp_settings = typed_queries.smtp.settings()
    smtp_client = SmtpClient(
        server=get_smtp_server_connection(
            secret_reader=SecretReader(settings=queries.get_secret_reader_settings()),
            secret=smtp_settings.credentials,
        ),
        mail_address=smtp_settings.mail_address,
        timeout=smtp_settings.timeout or DEFAULT_SMTP_TIMEOUT,
    )
    users = queries.get_users()
    g = init_github()

    results = threaded.run(get_user_company, users, thread_pool_size, github=g)

    users_to_delete = get_users_to_delete(results)

    if not dry_run and enable_deletion:
        mr_cli = mr_client_gateway.init(gitlab_project_id=gitlab_project_id)
        if defer:
            defer(mr_cli.cleanup)

    for user in users_to_delete:
        username = user["username"]
        paths = user["paths"]
        logging.info(["delete_user", username])

        if not dry_run:
            if send_mails:
                send_email_notification(user, smtp_client)
            elif enable_deletion:
                mr = CreateDeleteUserAppInterface(username, paths)
                mr.submit(cli=mr_cli)
            else:
                msg = (
                    "'delete' action is not enabled. "
                    "Please run the integration manually "
                    "with the '--enable-deletion' flag."
                )
                logging.warning(msg)
