import re
import string

from pydantic import BaseModel

from reconcile.utils.merge_request_manager.parser import Parser

PROMOTION_DATA_SEPARATOR = "**DO NOT MANUALLY CHANGE ANYTHING BELOW THIS LINE**"
VERSION = "1.0.0"
LABEL = "terraform-init"

VERSION_REF = "tf_init_version"
ACCOUNT_REF = "account"
COMPILED_REGEXES = {
    i: re.compile(rf".*{i}: (.*)$", re.MULTILINE) for i in [VERSION_REF, ACCOUNT_REF]
}

DESC = string.Template(
    f"""
This MR is triggered by app-interface's [terraform-init](https://github.com/app-sre/qontract-reconcile/tree/master/reconcile/terraform_init).

Please **do not remove** the **{LABEL}** label from this MR!

Parts of this description are used by integration to manage the MR.

{PROMOTION_DATA_SEPARATOR}

* {VERSION_REF}: {VERSION}
* {ACCOUNT_REF}: $account
"""
)


class Info(BaseModel):
    account: str


def create_parser() -> Parser:
    """Create a parser for MRs created by terraform-init."""

    return Parser[Info](
        klass=Info,
        compiled_regexes=COMPILED_REGEXES,
        version_ref=VERSION_REF,
        expected_version=VERSION,
        data_separator=PROMOTION_DATA_SEPARATOR,
    )


class Renderer:
    """This class is only concerned with rendering text for MRs."""

    def render_description(self, account: str) -> str:
        return DESC.safe_substitute(account=account)

    def render_title(self, account: str) -> str:
        return f"[auto] Terraform State settings for AWS account {account}"
