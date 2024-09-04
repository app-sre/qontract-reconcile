import pytest

from tools.cli_commands.erv2 import TfResource, TfResourceList


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
            # real life examples
            TfResource(
                address="aws_secretsmanager_secret.AmazonMSK_playground-msk-stage-playground-msk-stage"
            ),
            TfResource(
                address="aws_secretsmanager_secret.AmazonMSK_playground-msk-stage-playground-msk-stage-another-user"
            ),
            TfResource(address="aws_secretsmanager_secret.playground-user"),
            TfResource(address="aws_secretsmanager_secret.foobar-playground-user"),
        ]
    )
    assert len(terraform_resource_list) == 10
    # exact match
    assert terraform_resource_list[TfResource(address="exact-module.identifier")] == [
        TfResource(address="exact-module.identifier")
    ]
    # with postfix
    assert terraform_resource_list[
        TfResource(address="postfix-module.user-1-postfix")
    ] == [TfResource(address="postfix-module.user-1")]
    # with prefix
    assert terraform_resource_list[
        TfResource(address="prefix-module.prefix-user-1")
    ] == [TfResource(address="prefix-module.user-1")]

    # real life examples
    assert terraform_resource_list[
        TfResource(
            address="aws_secretsmanager_secret.AmazonMSK_playground-msk-stage-playground-msk-stage-secret"
        )
    ] == [
        TfResource(
            address="aws_secretsmanager_secret.AmazonMSK_playground-msk-stage-playground-msk-stage"
        ),
        TfResource(
            address="aws_secretsmanager_secret.AmazonMSK_playground-msk-stage-playground-msk-stage-another-user"
        ),
    ]
    assert terraform_resource_list[
        TfResource(
            address="aws_secretsmanager_secret.AmazonMSK_playground-msk-stage-playground-msk-stage-another-user-secret"
        )
    ] == [
        TfResource(
            address="aws_secretsmanager_secret.AmazonMSK_playground-msk-stage-playground-msk-stage"
        ),
        TfResource(
            address="aws_secretsmanager_secret.AmazonMSK_playground-msk-stage-playground-msk-stage-another-user"
        ),
    ]

    assert terraform_resource_list[
        TfResource(address="aws_secretsmanager_secret.secret-foobar-playground-user")
    ] == [
        TfResource(address="aws_secretsmanager_secret.playground-user"),
        TfResource(address="aws_secretsmanager_secret.foobar-playground-user"),
    ]
    with pytest.raises(KeyError):
        # unknown resource type
        terraform_resource_list[TfResource(address="not.found")]

    assert (
        terraform_resource_list[TfResource(address="aws_secretsmanager_secret.found")]
        == []
    )
