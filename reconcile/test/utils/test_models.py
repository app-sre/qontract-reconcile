from typing import Any

import pytest
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    Json,
    ValidationError,
    field_validator,
)

from reconcile.gql_definitions.fragments.vault_secret import VaultSecret
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


def test_csv_type() -> None:
    assert CSVModel(csv="a,b,c").csv == ["a", "b", "c"]
    assert CSVModel(csv="a").csv == ["a"]


def test_csv_type_empty() -> None:
    assert CSVModel(csv="").csv == []


class ConstrainedCSVModel(BaseModel):
    csv: CSV = Field(min_length=2, max_length=3)


def test_constrained_csv_type() -> None:
    ConstrainedCSVModel(csv="a,b")
    ConstrainedCSVModel(csv="a,b,c")


def test_constrained_csv_type_min_violation() -> None:
    with pytest.raises(ValidationError):
        ConstrainedCSVModel(csv="a")


def test_constrained_csv_type_max_violation() -> None:
    with pytest.raises(ValidationError):
        ConstrainedCSVModel(csv="a,b,c,d")


#
# pydantic cron custom type
#


class CronModel(BaseModel):
    cron: str
    _cron_validator = field_validator("cron")(cron_validator)


def test_cron_validation() -> None:
    CronModel(cron="0 * * * 1-5")


def test_cron_validation_invalid() -> None:
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
    data: dict[str, Any], expected_value: str | None
) -> None:
    """
    Optional string fields are not overwritten by default_data_none.
    """

    class DemoModel(BaseModel):
        optional_string: str | None = Field(...)

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
    data: dict[str, Any], field_default: int, expected_value: int
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
    data: dict[str, Any], expected_value: int | None
) -> None:
    """
    Optional int fields are not overwritten by default_data_none.
    """

    class DemoModel(BaseModel):
        optional_int: int | None = Field(...)

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
    data: dict[str, Any], expected_value: bool | None
) -> None:
    """
    Optional bool fields are not overwritten by default_data_none.
    """

    class DemoModel(BaseModel):
        optional_bool: bool | None = Field(...)

    assert (
        DemoModel(**data_default_none(DemoModel, data)).optional_bool == expected_value
    )


def test_default_fail_not_set() -> None:
    """
    Test that the exception is raised if value is not set and use_defaults is False.
    """

    class DemoModel(BaseModel):
        required_str: str = Field(...)

    with pytest.raises(ValueError):
        DemoModel(**data_default_none(DemoModel, {}, use_defaults=False))


def test_default_data_none_json() -> None:
    """
    Optional bool fields are not overwritten by default_data_none.
    """

    class DemoModel(BaseModel):
        mandatory_json: Json

    assert DemoModel(
        **data_default_none(DemoModel, {"mandatory_json": '{"a": 1}'})
    ).mandatory_json == {"a": 1}


@pytest.mark.parametrize(
    "data, expected_value",
    [
        ({}, None),
        ({"optional_json": '{"a": 1}'}, {"a": 1}),
    ],
)
def test_default_data_none_optional_json(
    data: dict[str, Any], expected_value: Json | None
) -> None:
    """
    Optional json fields are not overwritten by default_data_none.
    """

    class DemoModel(BaseModel):
        optional_json: Json | None

    assert (
        DemoModel(**data_default_none(DemoModel, data)).optional_json == expected_value
    )


#
# default data none - BaseModel field handling
#


class DemoFieldModel(BaseModel):
    demo_field: str
    field: str

    model_config = ConfigDict(extra="forbid")


class AnotherDemoFieldModel(BaseModel):
    another_demo_field: str
    field: str

    model_config = ConfigDict(extra="forbid")


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
    "data, expected_model_class, extected_field_data",
    [
        (
            {"model_field": {"demo_field": "test", "field": "test"}},
            DemoFieldModel,
            {"demo_field": "test", "field": "test"},
        ),
        (
            {"model_field": {"demo_field": "test"}},
            DemoFieldModel,
            {"demo_field": "test", "field": DEFAULT_STRING},
        ),
        (
            {"model_field": {"another_demo_field": "test", "field": "test"}},
            AnotherDemoFieldModel,
            {"another_demo_field": "test", "field": "test"},
        ),
        (
            {"model_field": {"another_demo_field": "test"}},
            AnotherDemoFieldModel,
            {"another_demo_field": "test", "field": DEFAULT_STRING},
        ),
        # no data is provided - the first applicable item from the smart union wins
        (
            {"model_field": {}},
            DemoFieldModel,
            {"demo_field": DEFAULT_STRING, "field": DEFAULT_STRING},
        ),
    ],
)
def test_default_data_none_mandatory_union_basemodel(
    data: dict[str, Any],
    expected_model_class: type[DemoFieldModel | AnotherDemoFieldModel],
    extected_field_data: dict[str, Any],
) -> None:
    """
    Make sure that defaults are applied to BaseModels smart unions.
    """

    class DemoModel(BaseModel):
        model_field: DemoFieldModel | AnotherDemoFieldModel

        model_config = ConfigDict(extra="forbid")

    d = DemoModel(**data_default_none(DemoModel, data))
    assert isinstance(d.model_field, expected_model_class)
    assert d.model_field.model_dump() == extected_field_data


@pytest.mark.parametrize(
    "data, expected_value",
    [
        ({"fields": [{}]}, DEFAULT_STRING),
        ({"fields": [{"field": "foobar"}]}, "foobar"),
    ],
)
def test_default_data_none_mandatory_basemodel_list_without_default(
    data: dict[str, Any], expected_value: str
) -> None:
    """
    Make sure that defaults are applied to BaseModels in lists
    """

    class DemoModel(BaseModel):
        fields: list[DemoFieldModel]

    assert (
        DemoModel(**data_default_none(DemoModel, data)).fields[0].field
        == expected_value
    )


def test_default_data_none_mandatory_union_basemodel_list_without_default() -> None:
    """
    Make sure that defaults are applied to smart union BaseModels lists
    """

    class DemoModel(BaseModel):
        fields: list[DemoFieldModel | AnotherDemoFieldModel]

    dm = DemoModel(
        **data_default_none(
            DemoModel,
            {
                "fields": [
                    {"demo_field": "test"},
                    {"another_demo_field": "test"},
                ]
            },
        )
    )

    assert isinstance(dm.fields[0], DemoFieldModel)
    assert dm.fields[0].demo_field == "test"
    assert dm.fields[0].field == DEFAULT_STRING

    assert isinstance(dm.fields[1], AnotherDemoFieldModel)
    assert dm.fields[1].another_demo_field == "test"
    assert dm.fields[1].field == DEFAULT_STRING


@pytest.mark.parametrize(
    "data, expected_values",
    [
        (
            {
                "sub_model": {
                    "requiredString": "value",
                },
                "Field": "field_value",
            },
            ["value", None, "field_value", None],
        ),
        (
            {
                "sub_model": {
                    "requiredString": "value1",
                    "optionalString": "value2",
                },
                "Field": "field_value",
                "optionalField": "optional_value",
            },
            ["value1", "value2", "field_value", "optional_value"],
        ),
    ],
)
def test_default_data_none_with_alias(
    data: dict[str, Any], expected_values: list[str | None]
) -> None:
    class SubModel(BaseModel):
        required_string: str = Field(..., alias="requiredString")
        optional_string: str | None = Field(..., alias="optionalString")

    class DemoModel(BaseModel):
        sub_model: SubModel
        field: str = Field(..., alias="Field")
        optional_field: str | None = Field(..., alias="optionalField")

    demo_model = DemoModel(**data_default_none(DemoModel, data))
    assert demo_model.sub_model.required_string == expected_values[0]
    assert demo_model.sub_model.optional_string == expected_values[1]
    assert demo_model.field == expected_values[2]
    assert demo_model.optional_field == expected_values[3]


@pytest.mark.parametrize(
    "data, expected_values",
    [
        (
            {
                "server": {
                    "token": {
                        "path": "vault/path/token",
                        "field": "token",
                    }
                }
            },
            ["vault/path/token", "token", None, None],
        ),
        (
            {
                "server": {
                    "token": {
                        "path": "vault/path/token",
                        "field": "token",
                        "version": 2,
                        "format": "json",
                    }
                }
            },
            ["vault/path/token", "token", 2, "json"],
        ),
    ],
)
def test_default_data_none_with_referenced_sub_basemodel(
    data: dict[str, Any], expected_values: list[str | None]
) -> None:
    class JiraServerV1(BaseModel):
        server_url: str = Field(..., alias="serverUrl")
        email: VaultSecret | None = Field(..., alias="email")
        token: VaultSecret = Field(..., alias="token")

    class DemoModel(BaseModel):
        path: str = Field(..., alias="path")
        name: str = Field(..., alias="name")
        server: JiraServerV1 = Field(..., alias="server")

    demo_model = DemoModel(**data_default_none(DemoModel, data))
    assert demo_model.server.token.path == expected_values[0]
    assert demo_model.server.token.field == expected_values[1]
    assert demo_model.server.token.version == expected_values[2]
    assert demo_model.server.token.q_format == expected_values[3]
