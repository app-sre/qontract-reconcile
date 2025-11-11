"""
Comprehensive tests for data_default_none function.

Tests are organized by field type for clarity and maintainability.
Each section tests a specific aspect of the data_default_none functionality.
"""

from typing import Any

import pytest
from pydantic import (
    BaseModel,
    Field,
    Json,
    ValidationError,
    field_validator,
)

from reconcile.gql_definitions.fragments.vault_secret import VaultSecret
from reconcile.utils.models import (
    CSV,
    DEFAULT_BOOL,
    DEFAULT_INT,
    DEFAULT_JSON,
    DEFAULT_STRING,
    cron_validator,
    data_default_none,
)

# =============================================================================
# Shared Test Helper Models
# =============================================================================


class SimpleModel(BaseModel, extra="forbid"):
    """Simple model with two fields for testing nested scenarios."""

    field_str: str
    field_int: int


class AlternativeModel(BaseModel, extra="forbid"):
    """Alternative model for testing union scenarios."""

    alt_field: str
    field_int: int


# =============================================================================
# 1. Custom Type Tests (CSV, Cron)
# =============================================================================


class CSVModel(BaseModel):
    csv: CSV


class ConstrainedCSVModel(BaseModel):
    csv: CSV = Field(min_length=2, max_length=3)


class CronModel(BaseModel):
    cron: str
    _cron_validator = field_validator("cron")(cron_validator)


@pytest.mark.parametrize(
    "csv_input, expected",
    [
        ("a,b,c", ["a", "b", "c"]),
        ("a", ["a"]),
        ("", []),
    ],
)
def test_csv_type(csv_input: str, expected: list[str]) -> None:
    """Test CSV custom type conversion."""
    assert CSVModel(csv=csv_input).csv == expected


def test_constrained_csv_type() -> None:
    ConstrainedCSVModel(csv="a,b")
    ConstrainedCSVModel(csv="a,b,c")


def test_constrained_csv_type_min_violation() -> None:
    with pytest.raises(ValidationError):
        ConstrainedCSVModel(csv="a")


def test_constrained_csv_type_max_violation() -> None:
    with pytest.raises(ValidationError):
        ConstrainedCSVModel(csv="a,b,c,d")


def test_cron_validation() -> None:
    CronModel(cron="0 * * * 1-5")


def test_cron_validation_invalid() -> None:
    with pytest.raises(ValidationError):
        CronModel(cron="0 48 * * 1-5")


# =============================================================================
# 2. Primitive Field Tests (str, int, bool)
# =============================================================================


class MandatoryStrModel(BaseModel, extra="forbid"):
    field: str


class StrWithDefaultModel(BaseModel, extra="forbid"):
    field: str = "default"


class OptionalStrModel(BaseModel, extra="forbid"):
    field: str | None


class OptionalStrWithDefaultModel(BaseModel, extra="forbid"):
    field: str | None = "default"


class MandatoryIntModel(BaseModel, extra="forbid"):
    field: int


class IntWithDefaultModel(BaseModel, extra="forbid"):
    field: int = 10


class OptionalIntModel(BaseModel, extra="forbid"):
    field: int | None


class OptionalIntWithDefaultModel(BaseModel, extra="forbid"):
    field: int | None = 42


class MandatoryBoolModel(BaseModel, extra="forbid"):
    field: bool


class BoolWithDefaultModel(BaseModel, extra="forbid"):
    field: bool = True


class OptionalBoolModel(BaseModel, extra="forbid"):
    field: bool | None


class OptionalBoolWithDefaultModel(BaseModel, extra="forbid"):
    field: bool | None = True


@pytest.mark.parametrize(
    "model_cls, input_data, expected",
    [
        # String tests
        (MandatoryStrModel, {}, DEFAULT_STRING),
        (MandatoryStrModel, {"field": "value"}, "value"),
        (StrWithDefaultModel, {}, "default"),
        (StrWithDefaultModel, {"field": "value"}, "value"),
        (OptionalStrModel, {}, None),
        (OptionalStrModel, {"field": "value"}, "value"),
        (OptionalStrWithDefaultModel, {}, "default"),
        (OptionalStrWithDefaultModel, {"field": "value"}, "value"),
        # Integer tests
        (MandatoryIntModel, {}, DEFAULT_INT),
        (MandatoryIntModel, {"field": 5}, 5),
        (IntWithDefaultModel, {}, 10),
        (IntWithDefaultModel, {"field": 5}, 5),
        (OptionalIntModel, {}, None),
        (OptionalIntModel, {"field": 5}, 5),
        (OptionalIntWithDefaultModel, {}, 42),
        (OptionalIntWithDefaultModel, {"field": 5}, 5),
        # Boolean tests
        (MandatoryBoolModel, {}, DEFAULT_BOOL),
        (MandatoryBoolModel, {"field": True}, True),
        (BoolWithDefaultModel, {}, True),
        (BoolWithDefaultModel, {"field": False}, False),
        (OptionalBoolModel, {}, None),
        (OptionalBoolModel, {"field": True}, True),
        (OptionalBoolWithDefaultModel, {}, True),
        (OptionalBoolWithDefaultModel, {"field": False}, False),
    ],
)
def test_primitive_fields(
    model_cls: type[
        MandatoryStrModel
        | StrWithDefaultModel
        | OptionalStrModel
        | OptionalStrWithDefaultModel
        | MandatoryIntModel
        | IntWithDefaultModel
        | OptionalIntModel
        | OptionalIntWithDefaultModel
        | MandatoryBoolModel
        | BoolWithDefaultModel
        | OptionalBoolModel
        | OptionalBoolWithDefaultModel
    ],
    input_data: dict[str, Any],
    expected: Any,
) -> None:
    """Test primitive field types (str, int, bool) with various configurations."""
    result = data_default_none(model_cls, input_data)
    assert isinstance(result, dict)
    model_instance = model_cls(**result)
    assert model_instance.field == expected


# =============================================================================
# 3. List Field Tests
# =============================================================================


class MandatoryListStrModel(BaseModel, extra="forbid"):
    field: list[str]


class ListStrWithDefaultModel(BaseModel, extra="forbid"):
    field: list[str] = ["default1", "default2"]


class MandatoryListUnionModel(BaseModel, extra="forbid"):
    field: list[str | int]


class ListUnionWithDefaultModel(BaseModel, extra="forbid"):
    field: list[str | int] = ["default", 1]


class OptionalListStrModel(BaseModel, extra="forbid"):
    field: list[str] | None


class OptionalListStrWithDefaultModel(BaseModel, extra="forbid"):
    field: list[str] | None = ["default1"]


@pytest.mark.parametrize(
    "model_cls, input_data, expected",
    [
        # Mandatory list[str]
        (MandatoryListStrModel, {}, []),
        (MandatoryListStrModel, {"field": ["a", "b"]}, ["a", "b"]),
        (ListStrWithDefaultModel, {}, ["default1", "default2"]),
        (ListStrWithDefaultModel, {"field": ["a"]}, ["a"]),
        # Union list[str | int]
        (MandatoryListUnionModel, {}, []),
        (MandatoryListUnionModel, {"field": ["a", 1]}, ["a", 1]),
        (ListUnionWithDefaultModel, {}, ["default", 1]),
        (ListUnionWithDefaultModel, {"field": ["x", 2]}, ["x", 2]),
        # Optional list
        (OptionalListStrModel, {}, None),
        (OptionalListStrModel, {"field": ["a"]}, ["a"]),
        (OptionalListStrWithDefaultModel, {}, ["default1"]),
        (OptionalListStrWithDefaultModel, {"field": ["a"]}, ["a"]),
    ],
)
def test_list_primitive_fields(
    model_cls: type[
        MandatoryListStrModel
        | ListStrWithDefaultModel
        | MandatoryListUnionModel
        | ListUnionWithDefaultModel
        | OptionalListStrModel
        | OptionalListStrWithDefaultModel
    ],
    input_data: dict[str, Any],
    expected: Any,
) -> None:
    """Test list fields with primitive types."""
    result = data_default_none(model_cls, input_data)
    assert isinstance(result, dict)
    model_instance = model_cls(**result)
    assert model_instance.field == expected


# =============================================================================
# 4. Nested List Tests (list[list[...]])
# =============================================================================


class NestedListModel(BaseModel, extra="forbid"):
    field: list[list[str]]


class OptionalNestedListModel(BaseModel, extra="forbid"):
    field: list[list[str]] | None


class DeeplyNestedListModel(BaseModel, extra="forbid"):
    field: list[list[list[str]]]


class OptionalDeeplyNestedListModel(BaseModel, extra="forbid"):
    field: list[list[list[str]]] | None


@pytest.mark.parametrize(
    "model_cls, input_data, expected",
    [
        # list[list[str]]
        (NestedListModel, {}, []),
        (NestedListModel, {"field": []}, []),
        (NestedListModel, {"field": [["a", "b"], ["c"]]}, [["a", "b"], ["c"]]),
        (NestedListModel, {"field": [[]]}, [[]]),
        (OptionalNestedListModel, {}, None),
        (OptionalNestedListModel, {"field": [["a"]]}, [["a"]]),
        # list[list[list[str]]]
        (DeeplyNestedListModel, {}, []),
        (DeeplyNestedListModel, {"field": [[[]]]}, [[[]]]),
        (DeeplyNestedListModel, {"field": [[["a"]]]}, [[["a"]]]),
        (DeeplyNestedListModel, {"field": [[["a"]], [["b"]]]}, [[["a"]], [["b"]]]),
        (
            DeeplyNestedListModel,
            {"field": [[["a", "b"], ["c", "d"]]]},
            [[["a", "b"], ["c", "d"]]],
        ),
        (OptionalDeeplyNestedListModel, {}, None),
        (OptionalDeeplyNestedListModel, {"field": [[["a"]]]}, [[["a"]]]),
    ],
)
def test_nested_lists(
    model_cls: type[
        NestedListModel
        | OptionalNestedListModel
        | DeeplyNestedListModel
        | OptionalDeeplyNestedListModel
    ],
    input_data: dict[str, Any],
    expected: Any,
) -> None:
    """Test nested list structures."""
    result = data_default_none(model_cls, input_data)
    assert isinstance(result, dict)
    model_instance = model_cls(**result)
    assert model_instance.field == expected


# =============================================================================
# 5. Dict Field Tests
# =============================================================================


class MandatoryDictStrStrModel(BaseModel, extra="forbid"):
    field: dict[str, str]


class DictStrStrWithDefaultModel(BaseModel, extra="forbid"):
    field: dict[str, str] = {"k": "v"}


class OptionalDictStrStrModel(BaseModel, extra="forbid"):
    field: dict[str, str] | None


class OptionalDictStrStrWithDefaultModel(BaseModel, extra="forbid"):
    field: dict[str, str] | None = {"k": "v"}


class MandatoryDictStrAnyModel(BaseModel, extra="forbid"):
    field: dict[str, Any]


class OptionalDictStrAnyModel(BaseModel, extra="forbid"):
    field: dict[str, Any] | None


class MandatoryDictStrIntModel(BaseModel, extra="forbid"):
    field: dict[str, int]


class OptionalDictStrIntModel(BaseModel, extra="forbid"):
    field: dict[str, int] | None


@pytest.mark.parametrize(
    "model_cls, input_data, expected",
    [
        # dict[str, str]
        (MandatoryDictStrStrModel, {"field": {}}, {}),
        (MandatoryDictStrStrModel, {"field": {"key": "value"}}, {"key": "value"}),
        (
            MandatoryDictStrStrModel,
            {"field": {"k1": "v1", "k2": "v2"}},
            {"k1": "v1", "k2": "v2"},
        ),
        (DictStrStrWithDefaultModel, {}, {"k": "v"}),
        (DictStrStrWithDefaultModel, {"field": {"new": "val"}}, {"new": "val"}),
        (OptionalDictStrStrModel, {}, None),
        (OptionalDictStrStrModel, {"field": {}}, {}),
        (OptionalDictStrStrModel, {"field": {"k": "v"}}, {"k": "v"}),
        (OptionalDictStrStrWithDefaultModel, {}, {"k": "v"}),
        (OptionalDictStrStrWithDefaultModel, {"field": {"x": "y"}}, {"x": "y"}),
        # dict[str, Any]
        (MandatoryDictStrAnyModel, {"field": {}}, {}),
        (MandatoryDictStrAnyModel, {"field": {"key": "string"}}, {"key": "string"}),
        (MandatoryDictStrAnyModel, {"field": {"key": 42}}, {"key": 42}),
        (MandatoryDictStrAnyModel, {"field": {"key": True}}, {"key": True}),
        (MandatoryDictStrAnyModel, {"field": {"key": ["list"]}}, {"key": ["list"]}),
        (
            MandatoryDictStrAnyModel,
            {"field": {"mixed": "types", "count": 5}},
            {"mixed": "types", "count": 5},
        ),
        (OptionalDictStrAnyModel, {}, None),
        (OptionalDictStrAnyModel, {"field": {}}, {}),
        (OptionalDictStrAnyModel, {"field": {"k": 1}}, {"k": 1}),
        # dict[str, int]
        (MandatoryDictStrIntModel, {"field": {}}, {}),
        (MandatoryDictStrIntModel, {"field": {"count": 42}}, {"count": 42}),
        (MandatoryDictStrIntModel, {"field": {"a": 1, "b": 2}}, {"a": 1, "b": 2}),
        (OptionalDictStrIntModel, {}, None),
        (OptionalDictStrIntModel, {"field": {}}, {}),
        (OptionalDictStrIntModel, {"field": {"k": 1}}, {"k": 1}),
    ],
)
def test_dict_fields(
    model_cls: type[
        MandatoryDictStrStrModel
        | DictStrStrWithDefaultModel
        | OptionalDictStrStrModel
        | OptionalDictStrStrWithDefaultModel
        | MandatoryDictStrAnyModel
        | OptionalDictStrAnyModel
        | MandatoryDictStrIntModel
        | OptionalDictStrIntModel
    ],
    input_data: dict[str, Any],
    expected: Any,
) -> None:
    """Test dict field types."""
    result = data_default_none(model_cls, input_data)
    assert isinstance(result, dict)
    model_instance = model_cls(**result)
    assert model_instance.field == expected


def test_dict_empty_vs_none() -> None:
    """Test that empty dict {} is different from None for optional dicts."""
    # No field provided -> None
    result_none = data_default_none(OptionalDictStrStrModel, {})
    assert isinstance(result_none, dict)
    model_none = OptionalDictStrStrModel(**result_none)
    assert model_none.field is None

    # Empty dict provided -> empty dict
    result_empty = data_default_none(OptionalDictStrStrModel, {"field": {}})
    assert isinstance(result_empty, dict)
    model_empty = OptionalDictStrStrModel(**result_empty)
    assert model_empty.field == {}


# =============================================================================
# 6. JSON Field Tests
# =============================================================================


class JsonFieldModel(BaseModel, extra="forbid"):
    field: Json


class OptionalJsonFieldModelNoDefault(BaseModel, extra="forbid"):
    field: Json | None


class OptionalJsonFieldModel(BaseModel, extra="forbid"):
    field: Json | None = None


@pytest.mark.parametrize(
    "model_cls, input_data, expected",
    [
        (JsonFieldModel, {}, DEFAULT_JSON),
        (JsonFieldModel, {"field": '{"a": 1}'}, {"a": 1}),
        (OptionalJsonFieldModel, {}, None),
        (OptionalJsonFieldModel, {"field": '{"a": 1}'}, {"a": 1}),
        (OptionalJsonFieldModelNoDefault, {}, None),
    ],
)
def test_json_fields(
    model_cls: type[JsonFieldModel | OptionalJsonFieldModel],
    input_data: dict[str, Any],
    expected: Any,
) -> None:
    """Test JSON field type."""
    result = data_default_none(model_cls, input_data)
    assert isinstance(result, dict)
    model_instance = model_cls(**result)
    assert model_instance.field == expected


# =============================================================================
# 7. Nested BaseModel Tests
# =============================================================================


class MandatoryNestedModel(BaseModel, extra="forbid"):
    nested: SimpleModel


class OptionalNestedModel(BaseModel, extra="forbid"):
    nested: SimpleModel | None


@pytest.mark.parametrize(
    "nested_data, expected_str, expected_int",
    [
        ({}, DEFAULT_STRING, DEFAULT_INT),
        ({"field_str": "test"}, "test", DEFAULT_INT),
        ({"field_str": "test", "field_int": 5}, "test", 5),
    ],
)
def test_nested_basemodel_mandatory(
    nested_data: dict[str, Any], expected_str: str, expected_int: int
) -> None:
    """Test mandatory nested BaseModel fields."""
    result = data_default_none(MandatoryNestedModel, {"nested": nested_data})
    assert isinstance(result, dict)
    model_instance = MandatoryNestedModel(**result)
    assert model_instance.nested.field_str == expected_str
    assert model_instance.nested.field_int == expected_int


@pytest.mark.parametrize(
    "input_data, is_none, expected_str, expected_int",
    [
        ({}, True, None, None),
        ({"nested": {}}, False, DEFAULT_STRING, DEFAULT_INT),
        ({"nested": {"field_str": "test"}}, False, "test", DEFAULT_INT),
        ({"nested": {"field_str": "test", "field_int": 5}}, False, "test", 5),
    ],
)
def test_nested_basemodel_optional(
    input_data: dict[str, Any],
    is_none: bool,
    expected_str: str | None,
    expected_int: int | None,
) -> None:
    """Test optional nested BaseModel fields."""
    result = data_default_none(OptionalNestedModel, input_data)
    assert isinstance(result, dict)
    model_instance = OptionalNestedModel(**result)

    if is_none:
        assert model_instance.nested is None
    else:
        assert model_instance.nested is not None
        assert model_instance.nested.field_str == expected_str
        assert model_instance.nested.field_int == expected_int


# =============================================================================
# 8. List of BaseModel Tests
# =============================================================================


class ListOfModelsModel(BaseModel, extra="forbid"):
    items: list[SimpleModel]


@pytest.mark.parametrize(
    "items_data, expected_values",
    [
        ([], []),
        ([{"field_str": "test"}], [("test", DEFAULT_INT)]),
        ([{"field_str": "test", "field_int": 5}], [("test", 5)]),
        (
            [{"field_str": "a"}, {"field_str": "b", "field_int": 10}],
            [("a", DEFAULT_INT), ("b", 10)],
        ),
    ],
)
def test_list_of_basemodels(
    items_data: list[dict[str, Any]], expected_values: list[tuple[str, int]]
) -> None:
    """Test list of BaseModel instances."""
    result = data_default_none(ListOfModelsModel, {"items": items_data})
    assert isinstance(result, dict)
    model_instance = ListOfModelsModel(**result)
    assert len(model_instance.items) == len(expected_values)
    for item, (exp_str, exp_int) in zip(
        model_instance.items, expected_values, strict=True
    ):
        assert item.field_str == exp_str
        assert item.field_int == exp_int


# =============================================================================
# 9. Union Type Tests
# =============================================================================


class UnionFieldModel(BaseModel, extra="forbid"):
    union_field: SimpleModel | AlternativeModel


class ListOfUnionModelsModel(BaseModel, extra="forbid"):
    items: list[SimpleModel | AlternativeModel]


class ListOfMixedUnionModel(BaseModel, extra="forbid"):
    items: list[SimpleModel | str]


@pytest.mark.parametrize(
    "union_data, expected_type, expected_dump",
    [
        (
            {"field_str": "test", "field_int": 5},
            SimpleModel,
            {"field_str": "test", "field_int": 5},
        ),
        (
            {"field_str": "test"},
            SimpleModel,
            {"field_str": "test", "field_int": DEFAULT_INT},
        ),
        (
            {"alt_field": "test", "field_int": 5},
            AlternativeModel,
            {"alt_field": "test", "field_int": 5},
        ),
        (
            {"alt_field": "test"},
            AlternativeModel,
            {"alt_field": "test", "field_int": DEFAULT_INT},
        ),
    ],
)
def test_union_basemodel_fields(
    union_data: dict[str, Any],
    expected_type: type[BaseModel],
    expected_dump: dict[str, Any],
) -> None:
    """Test union of BaseModel types."""
    result = data_default_none(UnionFieldModel, {"union_field": union_data})
    assert isinstance(result, dict)
    model_instance = UnionFieldModel(**result)
    assert isinstance(model_instance.union_field, expected_type)
    assert model_instance.union_field.model_dump() == expected_dump


def test_list_of_union_basemodels() -> None:
    """Test list containing union of BaseModel types."""
    input_data = {
        "items": [
            {"field_str": "simple", "field_int": 5},
            {"alt_field": "alternative", "field_int": 5},
            {"field_str": "simple2"},
            {"alt_field": "alternative2"},
        ]
    }

    result = data_default_none(ListOfUnionModelsModel, input_data)
    assert isinstance(result, dict)
    model_instance = ListOfUnionModelsModel(**result)

    assert len(model_instance.items) == 4
    assert isinstance(model_instance.items[0], SimpleModel)
    assert model_instance.items[0].field_str == "simple"
    assert model_instance.items[0].field_int == 5
    assert isinstance(model_instance.items[1], AlternativeModel)
    assert model_instance.items[1].alt_field == "alternative"
    assert model_instance.items[1].field_int == 5
    assert isinstance(model_instance.items[2], SimpleModel)
    assert model_instance.items[2].field_str == "simple2"
    assert model_instance.items[2].field_int == DEFAULT_INT
    assert isinstance(model_instance.items[3], AlternativeModel)
    assert model_instance.items[3].alt_field == "alternative2"
    assert model_instance.items[3].field_int == DEFAULT_INT


def test_list_of_mixed_union_basemodel_and_primitives() -> None:
    """Test list containing both BaseModel and primitive types."""
    input_data = {
        "items": [
            {"field_str": "model1"},
            "just a string",
            {"field_str": "model2", "field_int": 10},
        ]
    }

    result = data_default_none(ListOfMixedUnionModel, input_data)
    assert isinstance(result, dict)
    model_instance = ListOfMixedUnionModel(**result)

    assert len(model_instance.items) == 3
    assert isinstance(model_instance.items[0], SimpleModel)
    assert model_instance.items[0].field_str == "model1"
    assert model_instance.items[0].field_int == DEFAULT_INT
    assert isinstance(model_instance.items[1], str)
    assert model_instance.items[1] == "just a string"
    assert isinstance(model_instance.items[2], SimpleModel)
    assert model_instance.items[2].field_int == 10


# =============================================================================
# 10. Field Aliases Tests
# =============================================================================


class SubModelWithAlias(BaseModel, extra="forbid"):
    required_string: str = Field(..., alias="requiredString")
    optional_string: str | None = Field(..., alias="optionalString")


class ModelWithAliases(BaseModel, extra="forbid"):
    nested: SubModelWithAlias = Field(..., alias="nested")
    field: str = Field(..., alias="Field")
    optional_field: str | None = Field(..., alias="optionalField")


@pytest.mark.parametrize(
    "input_data, expected",
    [
        (
            {"nested": {"requiredString": "v1"}, "Field": "fval"},
            {"req": "v1", "opt": None, "field": "fval", "opt_field": None},
        ),
        (
            {
                "nested": {"requiredString": "v1", "optionalString": "v2"},
                "Field": "fval",
                "optionalField": "optval",
            },
            {"req": "v1", "opt": "v2", "field": "fval", "opt_field": "optval"},
        ),
    ],
)
def test_fields_with_aliases(
    input_data: dict[str, Any], expected: dict[str, Any]
) -> None:
    """Test fields with aliases."""
    result = data_default_none(ModelWithAliases, input_data)
    assert isinstance(result, dict)
    model_instance = ModelWithAliases(**result)

    assert model_instance.nested.required_string == expected["req"]
    assert model_instance.nested.optional_string == expected["opt"]
    assert model_instance.field == expected["field"]
    assert model_instance.optional_field == expected["opt_field"]


# =============================================================================
# 11. Definition References (VaultSecret) Tests
# =============================================================================


class ServerModelWithVault(BaseModel, extra="forbid"):
    server_url: str = Field(..., alias="serverUrl")
    email: VaultSecret | None = Field(..., alias="email")
    token: VaultSecret = Field(..., alias="token")


class ModelWithVaultReference(BaseModel, extra="forbid"):
    path: str = Field(..., alias="path")
    name: str = Field(..., alias="name")
    server: ServerModelWithVault | None = Field(..., alias="server")


@pytest.mark.parametrize(
    "input_data, expected_path, expected_field, expected_version, expected_format",
    [
        (
            {"server": {"token": {"path": "vault/path", "field": "token"}}},
            "vault/path",
            "token",
            None,
            None,
        ),
        (
            {
                "server": {
                    "token": {
                        "path": "vault/path",
                        "field": "token",
                        "version": 2,
                        "format": "json",
                    }
                }
            },
            "vault/path",
            "token",
            2,
            "json",
        ),
    ],
)
def test_definition_ref_fields(
    input_data: dict[str, Any],
    expected_path: str,
    expected_field: str,
    expected_version: int | None,
    expected_format: str | None,
) -> None:
    """Test definition-ref fields (e.g., VaultSecret)."""
    result = data_default_none(ModelWithVaultReference, input_data)
    assert isinstance(result, dict)
    model_instance = ModelWithVaultReference(**result)

    assert model_instance.server is not None
    assert model_instance.server.token.path == expected_path
    assert model_instance.server.token.field == expected_field
    assert model_instance.server.token.version == expected_version
    assert model_instance.server.token.q_format == expected_format


# =============================================================================
# 12. Special Cases and Edge Cases
# =============================================================================


class RequiredFieldModel(BaseModel, extra="forbid"):
    required_str: str = Field(...)


def test_use_defaults_false_raises_error() -> None:
    """Test use_defaults=False raises error for missing required fields."""
    with pytest.raises(ValueError, match="Field  is required but not set"):
        data_default_none(RequiredFieldModel, {}, use_defaults=False)


def test_use_defaults_false_allows_provided_values() -> None:
    """Test use_defaults=False works when values are provided."""
    result = data_default_none(
        RequiredFieldModel, {"required_str": "value"}, use_defaults=False
    )
    assert isinstance(result, dict)
    model_instance = RequiredFieldModel(**result)
    assert model_instance.required_str == "value"


class Level3Model(BaseModel, extra="forbid"):
    value: str


class Level2Model(BaseModel, extra="forbid"):
    nested: Level3Model


class Level1Model(BaseModel, extra="forbid"):
    nested: Level2Model


def test_deeply_nested_models() -> None:
    """Test deeply nested BaseModel structures (3+ levels)."""
    input_data: dict[str, dict[str, dict[str, Any]]] = {"nested": {"nested": {}}}
    result = data_default_none(Level1Model, input_data)
    assert isinstance(result, dict)
    model_instance = Level1Model(**result)
    assert model_instance.nested.nested.value == DEFAULT_STRING


class ComplexModel(BaseModel, extra="forbid"):
    str_field: str
    int_field: int
    bool_field: bool
    list_field: list[str]
    optional_field: str | None
    nested_field: SimpleModel


def test_complex_model_with_all_field_types() -> None:
    """Test model combining multiple field types."""
    result = data_default_none(ComplexModel, {})
    assert isinstance(result, dict)
    model_instance = ComplexModel(**result)

    assert model_instance.str_field == DEFAULT_STRING
    assert model_instance.int_field == DEFAULT_INT
    assert model_instance.bool_field == DEFAULT_BOOL
    assert model_instance.list_field == []
    assert model_instance.optional_field is None
    assert model_instance.nested_field.field_str == DEFAULT_STRING
    assert model_instance.nested_field.field_int == DEFAULT_INT
