from textwrap import dedent

from reconcile.terraform_init.merge_request import Renderer, create_parser
from reconcile.utils.merge_request_manager.parser import Parser


def test_terraform_init_merge_request_renderer_render_description() -> None:
    renderer = Renderer()
    assert renderer.render_description(account="account-name") == dedent("""
        This MR is triggered by app-interface's [terraform-init](https://github.com/app-sre/qontract-reconcile/tree/master/reconcile/terraform_init).

        Please **do not remove** the **terraform-init** label from this MR!

        Parts of this description are used by integration to manage the MR.

        **DO NOT MANUALLY CHANGE ANYTHING BELOW THIS LINE**

        * tf_init_version: 1.0.0
        * account: account-name
""")


def test_terraform_init_merge_request_renderer_render_title() -> None:
    renderer = Renderer()
    assert (
        renderer.render_title(account="account-name")
        == "[auto] Terraform State settings for AWS account account-name"
    )


def test_terraform_init_merge_request_create_parser() -> None:
    parser = create_parser()
    assert isinstance(parser, Parser)
