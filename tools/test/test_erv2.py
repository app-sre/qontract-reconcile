import pytest

from tools.cli_commands.erv2 import TfResource, TfResourceList


def test_erv2_model_tfresource() -> None:
    tfr1 = TfResource(address="aws_module.identifier")
    assert tfr1.type == "aws_module"
    assert tfr1.id == "identifier"
    tfr2 = TfResource(address="aws_module.identifier-with-postfix")
    assert tfr2 > tfr1


def test_erv2_model_tfresource_list() -> None:
    tfrl = TfResourceList(
        resources=[
            TfResource(address="postfix-module.identifier-postfix"),
            TfResource(address="prefix-module.prefix-identifier"),
            TfResource(address="exact-module.identifier"),
            TfResource(address="something.else"),
        ]
    )
    assert len(tfrl) == 4
    # exact match
    assert (
        tfrl[TfResource(address="exact-module.identifier")].address
        == "exact-module.identifier"
    )
    # with postfix
    assert (
        tfrl[TfResource(address="postfix-module.identifier")].address
        == "postfix-module.identifier-postfix"
    )
    # with prefix
    assert (
        tfrl[TfResource(address="prefix-module.identifier")].address
        == "prefix-module.prefix-identifier"
    )

    with pytest.raises(KeyError):
        tfrl[TfResource(address="not.found")]
