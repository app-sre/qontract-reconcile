from collections.abc import Mapping
from typing import (
    Any,
    Optional,
    Union,
)

import pytest
from pydantic import BaseModel
from pytest_mock import MockerFixture

from reconcile.utils.disabled_integrations import (
    HasDisableIntegrations,
    disabled_integrations,
    integration_is_enabled,
)


class IntMandatory(BaseModel):
    integrations: list[str]


class IntOptional(BaseModel):
    integrations: Optional[list[str]]


class MandatoryIntMandatory(BaseModel):
    disable: IntMandatory


class OptionalIntOptional(BaseModel):
    disable: Optional[IntOptional]


class MandatoryIntOptional(BaseModel):
    disable: IntOptional


class OptionalIntMandatory(BaseModel):
    disable: Optional[IntMandatory]


INT_LIST = ["int1", "int2"]


@pytest.mark.parametrize(
    "disable_obj, expected",
    [
        # classes
        (None, []),
        (
            MandatoryIntMandatory(disable=IntMandatory(integrations=INT_LIST)),
            INT_LIST,
        ),
        (OptionalIntOptional(disable=None), []),
        (OptionalIntOptional(disable=IntOptional(integrations=None)), []),
        (OptionalIntOptional(disable=IntOptional(integrations=INT_LIST)), INT_LIST),
        (MandatoryIntOptional(disable=IntOptional(integrations=None)), []),
        (MandatoryIntOptional(disable=IntOptional(integrations=INT_LIST)), INT_LIST),
        (OptionalIntMandatory(disable=None), []),
        (OptionalIntMandatory(disable=IntMandatory(integrations=INT_LIST)), INT_LIST),
        # dicts
        ({}, []),
        ({"disable": None}, []),
        ({"disable": {}}, []),
        ({"disable": {"integrations": None}}, []),
        ({"disable": {"integrations": []}}, []),
        ({"disable": {"integrations": INT_LIST}}, INT_LIST),
    ],
)
def test_utils_disabled_integrations(
    disable_obj: Optional[Union[Mapping[str, Any], HasDisableIntegrations]],
    expected: list[str],
) -> None:
    assert disabled_integrations(disable_obj) == expected


def test_utils_disabled_integrations_integration_is_enabled(
    mocker: MockerFixture,
) -> None:
    mocker.patch(
        "reconcile.utils.disabled_integrations.disabled_integrations",
        return_value=["int1"],
    )
    assert not integration_is_enabled("int1", None)
    assert integration_is_enabled("int2", None)
