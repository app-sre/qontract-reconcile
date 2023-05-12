from typing import (
    Any,
    Optional,
    Union,
)

import pytest
from pydantic import (
    BaseModel,
    Extra,
    Field,
    ValidationError,
    validator,
)

from reconcile.utils.models import (
    CSV,
    DEFAULT_INT,
    DEFAULT_STRING,
    cron_validator,
    data_default_none,
)

#
# pydantic CSV custom type
#


class CSVModel(BaseModel):
    csv: CSV


def test_csv_type():
    assert CSVModel(csv="a,b,c").csv == ["a", "b", "c"]
    assert CSVModel(csv="a").csv == ["a"]


def test_csv_type_empty():
    assert CSVModel(csv="").csv == []


class ConstrainedCSVModel(BaseModel):
    csv: CSV = Field(csv_min_items=2, csv_max_items=3)


def test_constrained_csv_type():
    ConstrainedCSVModel(csv="a,b")
    ConstrainedCSVModel(csv="a,b,c")


def test_constrained_csv_type_min_violation():
    with pytest.raises(ValidationError):
        ConstrainedCSVModel(csv="a")


def test_constrained_csv_type_max_violation():
    with pytest.raises(ValidationError):
        ConstrainedCSVModel(csv="a,b,c,d")


#
# pydantic cron custom type
#


class CronModel(BaseModel):
    cron: str
    _cron_validator = validator("cron", allow_reuse=True)(cron_validator)


def test_cron_validation():
    CronModel(cron="0 * * * 1-5")


def test_cron_validation_invalid():
    with pytest.raises(ValidationError):
        CronModel(cron="0 48 * * 1-5")


#
# default data none - string handling
#


@pytest.mark.parametrize(
    "data, expected_value",
    [
        ({}, DEFAULT_STRING),
        ({"mandatory_string": "value"}, "value"),
    ],
)
def test_default_data_none_mandatory_string_without_default(
    data: dict[str, Any], expected_value: str
) -> None:
    """
    Mandatory string fields without a default value are filled with a generic
    default string if they are not provided in the dictionary. If a value is
    present in the dictionary though, it is used and not overwritten.
    """

    class DemoModel(BaseModel):
        mandatory_string: str

    assert (
        DemoModel(**data_default_none(DemoModel, data)).mandatory_string
        == expected_value
    )


@pytest.mark.parametrize(
    "data, field_default, expected_value",
    [
        ({}, "field_default", "field_default"),
        ({"mandatory_string": "value"}, "field_default", "value"),
    ],
)
def test_default_data_none_mandatory_string_with_default(
    data: dict[str, Any], field_default: str, expected_value: str
) -> None:
    """
    Don't add fill the gap with a default value if the pydantic dataclass
    field already has a default value.
    """

    class DemoModel(BaseModel):
        mandatory_string: str = field_default

    assert (
        DemoModel(**data_default_none(DemoModel, data)).mandatory_string
        == expected_value
    )


@pytest.mark.parametrize(
    "data, expected_value",
    [
        ({}, None),
        ({"optional_string": "value"}, "value"),
    ],
)
def test_default_data_none_optional_string(
    data: dict[str, Any], expected_value: str
) -> None:
    """
    Optional string fields are not overwritten by default_data_none.
    """

    class DemoModel(BaseModel):
        optional_string: Optional[str] = Field(...)

    assert (
        DemoModel(**data_default_none(DemoModel, data)).optional_string
        == expected_value
    )


#
# default data none - int handling
#


@pytest.mark.parametrize(
    "data, expected_value",
    [
        ({}, DEFAULT_INT),
        ({"mandatory_int": 5}, 5),
    ],
)
def test_default_data_none_mandatory_int_without_default(
    data: dict[str, Any], expected_value: int
) -> None:
    """
    Mandatory int fields without a default value are filled with a generic
    default integer if they are not provided in the dictionary. If a value is
    present in the dictionary though, it is used and not overwritten.
    """

    class DemoModel(BaseModel):
        mandatory_int: int

    assert (
        DemoModel(**data_default_none(DemoModel, data)).mandatory_int == expected_value
    )


@pytest.mark.parametrize(
    "data, field_default, expected_value",
    [
        ({}, 5, 5),
        ({"mandatory_int": 5}, 10, 5),
    ],
)
def test_default_data_none_mandatory_int_with_default(
    data: dict[str, Any], field_default: int, expected_value: str
) -> None:
    """
    Don't add fill the gap with a default value if the pydantic dataclass
    field already has a default value.
    """

    class DemoModel(BaseModel):
        mandatory_int: int = field_default

    assert (
        DemoModel(**data_default_none(DemoModel, data)).mandatory_int == expected_value
    )


@pytest.mark.parametrize(
    "data, expected_value",
    [
        ({}, None),
        ({"optional_int": 5}, 5),
    ],
)
def test_default_data_none_optional_int(
    data: dict[str, Any], expected_value: int
) -> None:
    """
    Optional int fields are not overwritten by default_data_none.
    """

    class DemoModel(BaseModel):
        optional_int: Optional[int] = Field(...)

    assert (
        DemoModel(**data_default_none(DemoModel, data)).optional_int == expected_value
    )


#
# default data none - bool handling
#


@pytest.mark.parametrize(
    "data, expected_value",
    [
        ({}, False),
        ({"mandatory_bool": True}, True),
    ],
)
def test_default_data_none_mandatory_bool_without_default(
    data: dict[str, Any], expected_value: bool
) -> None:
    """
    Mandatory bool fields without a default value are filled with False
    if they are not provided in the dictionary. If a value is
    present in the dictionary though, it is used and not overwritten.
    """

    class DemoModel(BaseModel):
        mandatory_bool: bool

    assert (
        DemoModel(**data_default_none(DemoModel, data)).mandatory_bool == expected_value
    )


@pytest.mark.parametrize(
    "data, field_default, expected_value",
    [
        ({}, True, True),
        ({"mandatory_bool": False}, True, False),
    ],
)
def test_default_data_none_mandatory_bool_with_default(
    data: dict[str, Any], field_default: bool, expected_value: bool
) -> None:
    """
    Don't add fill the gap with a default value if the pydantic dataclass
    field already has a default value.
    """

    class DemoModel(BaseModel):
        mandatory_bool: bool = field_default

    assert (
        DemoModel(**data_default_none(DemoModel, data)).mandatory_bool == expected_value
    )


@pytest.mark.parametrize(
    "data, expected_value",
    [
        ({}, None),
        ({"optional_bool": True}, True),
    ],
)
def test_default_data_none_optional_bool(
    data: dict[str, Any], expected_value: bool
) -> None:
    """
    Optional bool fields are not overwritten by default_data_none.
    """

    class DemoModel(BaseModel):
        optional_bool: Optional[bool] = Field(...)

    assert (
        DemoModel(**data_default_none(DemoModel, data)).optional_bool == expected_value
    )


#
# default data none - BaseModel field handling
#


class DemoFieldModel(BaseModel):
    demo_field: str
    field: str

    class Config:
        smart_union = True
        extra = Extra.forbid


class AnotherDemoFieldModel(BaseModel):
    another_demo_field: str
    field: str

    class Config:
        smart_union = True
        extra = Extra.forbid


@pytest.mark.parametrize(
    "data, expected_value",
    [
        ({"model_field": {}}, DEFAULT_STRING),
    ],
)
def test_default_data_none_mandatory_basemodel(
    data: dict[str, Any], expected_value: str
) -> None:
    """
    Make sure that defaults are applied to BaseModels fields
    """

    class DemoModel(BaseModel):
        model_field: DemoFieldModel

    assert (
        DemoModel(**data_default_none(DemoModel, data)).model_field.field
        == expected_value
    )


@pytest.mark.parametrize(
    "data, expected_model_class_name, extected_field_data",
    [
        (
            {"model_field": {"demo_field": "test", "field": "test"}},
            "DemoFieldModel",
            {"demo_field": "test", "field": "test"},
        ),
        (
            {"model_field": {"demo_field": "test"}},
            "DemoFieldModel",
            {"demo_field": "test", "field": DEFAULT_STRING},
        ),
        (
            {"model_field": {"another_demo_field": "test", "field": "test"}},
            "AnotherDemoFieldModel",
            {"another_demo_field": "test", "field": "test"},
        ),
        (
            {"model_field": {"another_demo_field": "test"}},
            "AnotherDemoFieldModel",
            {"another_demo_field": "test", "field": DEFAULT_STRING},
        ),
        # no data is provided - the first applicable item from the smart union wins
        (
            {"model_field": {}},
            "DemoFieldModel",
            {"demo_field": DEFAULT_STRING, "field": DEFAULT_STRING},
        ),
    ],
)
def test_default_data_none_mandatory_union_basemodel(
    data: dict[str, Any],
    expected_model_class_name: str,
    extected_field_data: dict[str, Any],
) -> None:
    """
    Make sure that defaults are applied to BaseModels smart unions.
    """
    expected_model_class = globals()[expected_model_class_name]

    class DemoModel(BaseModel):
        model_field: Union[DemoFieldModel, AnotherDemoFieldModel]

        class Config:
            smart_union = True
            extra = Extra.forbid

    d = DemoModel(**data_default_none(DemoModel, data))
    assert isinstance(d.model_field, expected_model_class)
    assert d.model_field.dict() == extected_field_data


@pytest.mark.parametrize(
    "data, expected_value",
    [
        ({"model_fields": [{}]}, DEFAULT_STRING),
    ],
)
def test_default_data_none_mandatory_basemodel_list_without_default(
    data: dict[str, Any], expected_value: str
) -> None:
    """
    Make sure that defaults are applied to BaseModels in lists
    """

    class DemoModel(BaseModel):
        model_fields: list[DemoFieldModel]

    assert (
        DemoModel(**data_default_none(DemoModel, data)).model_fields[0].field
        == expected_value
    )


def test_default_data_none_mandatory_union_basemodel_list_without_default() -> None:
    """
    Make sure that defaults are applied to smart union BaseModels lists
    """

    class DemoModel(BaseModel):
        model_fields: list[Union[DemoFieldModel, AnotherDemoFieldModel]]

    dm = DemoModel(
        **data_default_none(
            DemoModel,
            {
                "model_fields": [
                    {"demo_field": "test"},
                    {"another_demo_field": "test"},
                ]
            },
        )
    )

    assert isinstance(dm.model_fields[0], DemoFieldModel)
    assert dm.model_fields[0].demo_field == "test"
    assert dm.model_fields[0].field == DEFAULT_STRING

    assert isinstance(dm.model_fields[1], AnotherDemoFieldModel)
    assert dm.model_fields[1].another_demo_field == "test"
    assert dm.model_fields[1].field == DEFAULT_STRING
