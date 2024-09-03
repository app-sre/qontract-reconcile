import pytest

from tools.cli_commands.erv2 import TfResource, TfResourceList


def test_erv2_model_tfresource() -> None:
    tfr1 = TfResource(address="aws_module.identifier")
    assert tfr1.type == "aws_module"
    assert tfr1.id == "identifier"
    tfr2 = TfResource(address="aws_module.identifier-with-postfix")
    assert tfr2 > tfr1


def test_erv2_model_tfresource_list() -> None:
    # terraform_resource_list
    terraform_resource_list = TfResourceList(
        resources=[
            TfResource(address="postfix-module.user-1"),
            TfResource(address="postfix-module.user-2"),
            TfResource(address="prefix-module.user-1"),
            TfResource(address="prefix-module.user-2"),
            TfResource(address="exact-module.identifier"),
            TfResource(address="something.else"),
            # real life example
            TfResource(
                address="aws_secretsmanager_secret.AmazonMSK_playground-msk-stage-playground-msk-stage"
            ),
            TfResource(
                address="aws_secretsmanager_secret.AmazonMSK_playground-msk-stage-playground-msk-stage-another-user"
            ),
        ]
    )
    assert len(terraform_resource_list) == 8
    # exact match
    assert (
        terraform_resource_list[TfResource(address="exact-module.identifier")].address
        == "exact-module.identifier"
    )
    # with postfix
    assert (
        terraform_resource_list[
            TfResource(address="postfix-module.user-1-postfix")
        ].address
        == "postfix-module.user-1"
    )
    # with prefix
    assert (
        terraform_resource_list[
            TfResource(address="prefix-module.prefix-user-1")
        ].address
        == "prefix-module.user-1"
    )
    # real life example
    assert (
        terraform_resource_list[
            TfResource(
                address="aws_secretsmanager_secret.AmazonMSK_playground-msk-stage-playground-msk-stage-secret"
            )
        ].address
        == "aws_secretsmanager_secret.AmazonMSK_playground-msk-stage-playground-msk-stage"
    )
    # test sorting in TfResourceList.__getitem__
    assert (
        terraform_resource_list[
            TfResource(
                address="aws_secretsmanager_secret.AmazonMSK_playground-msk-stage-playground-msk-stage-another-user-secret"
            )
        ].address
        == "aws_secretsmanager_secret.AmazonMSK_playground-msk-stage-playground-msk-stage-another-user"
    )
    with pytest.raises(KeyError):
        terraform_resource_list[TfResource(address="not.found")]
