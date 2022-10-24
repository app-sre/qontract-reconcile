from typing import Optional, Sequence

import pytest

from reconcile.gql_definitions.change_owners.queries.change_types import (
    ChangeTypeChangeDetectorContextSelectorV1,
    ChangeTypeChangeDetectorJsonPathProviderV1,
    ChangeTypeChangeDetectorV1,
    ChangeTypeV1,
    ChangeTypeV1_ChangeTypeV1,
)

from reconcile.change_owners.change_types import (
    BundleFileType,
    init_change_type_processors,
    ChangeTypeInheritanceCycleError,
    ChangeTypeIncompatibleInheritanceError,
)


def build_jsonpath_change(
    selectors: list[str],
    schema: Optional[str] = None,
    context_selector: Optional[str] = None,
    context_when: Optional[str] = None,
) -> ChangeTypeChangeDetectorJsonPathProviderV1:
    if context_selector:
        context = ChangeTypeChangeDetectorContextSelectorV1(
            selector=context_selector, when=context_when
        )
    else:
        context = None
    return ChangeTypeChangeDetectorJsonPathProviderV1(
        provider="jsonPath",
        changeSchema=schema,
        jsonPathSelectors=selectors,
        context=context,
    )


def build_def_change_type(
    name: str, inherit: Optional[list[str]] = None
) -> ChangeTypeV1:
    return ChangeTypeV1(
        name=name,
        contextType=BundleFileType.DATAFILE.value,
        contextSchema="context-schema",
        disabled=False,
        changes=[
            build_jsonpath_change(
                schema=f"/schema/change-schema-{name}",
                selectors=[f"selector.{name}"],
            )
        ],
        inherit=[ChangeTypeV1_ChangeTypeV1(name=i) for i in inherit or []],
    )


def test_change_type_no_inheritance():
    ct_1 = build_def_change_type("change-type-1")
    ct_2 = build_def_change_type("change-type-2")

    processors = init_change_type_processors([ct_1, ct_2])
    assert len(processors) == 2


def test_change_type_inheritance_cycle():
    ct_1 = build_def_change_type("change-type-1", inherit=["change-type-2"])
    ct_2 = build_def_change_type("change-type-2", inherit=["change-type-3"])
    ct_3 = build_def_change_type("change-type-3", inherit=["change-type-1"])

    with pytest.raises(ChangeTypeInheritanceCycleError) as e:
        init_change_type_processors([ct_1, ct_2, ct_3])
    assert e.value.args[0] == "Cycles detected in change-type inheritance"
    assert set(e.value.args[1][0]) == {ct_1.name, ct_2.name, ct_3.name}


def test_change_type_inheritance_context_schema_mismatch():
    """
    a mismatch in context schema in an inheritance chain should be detected
    """
    ct_1 = build_def_change_type("change-type-1", inherit=["change-type-2"])
    ct_1.context_schema = "schema-1"
    ct_2 = build_def_change_type("change-type-2")
    ct_2.context_schema = "schema-2"

    with pytest.raises(ChangeTypeIncompatibleInheritanceError):
        init_change_type_processors([ct_1, ct_2])


def test_change_type_inhertiance_no_context_schema():
    """
    missing context schema is ok as long as both change types
    in an inheritance chain miss it
    """
    ct_1 = build_def_change_type("change-type-1", inherit=["change-type-2"])
    ct_1.context_schema = None
    ct_2 = build_def_change_type("change-type-2")
    ct_2.context_schema = None

    init_change_type_processors([ct_1, ct_2])


def test_change_type_inheritance_context_type_mismatch():
    """
    all change types in an inheritance chain must have the same context type
    """
    ct_1 = build_def_change_type("change-type-1", inherit=["change-type-2"])
    ct_2 = build_def_change_type("change-type-2")
    ct_2.context_type = BundleFileType.RESOURCEFILE.value

    with pytest.raises(ChangeTypeIncompatibleInheritanceError):
        init_change_type_processors([ct_1, ct_2])


def test_change_type_single_level_inheritance():
    ct_1 = build_def_change_type(
        "change-type-1", inherit=["change-type-2", "change-type-3"]
    )
    ct_2 = build_def_change_type("change-type-2")
    ct_3 = build_def_change_type("change-type-3")

    processors = init_change_type_processors([ct_1, ct_2, ct_3])
    assert len(processors) == 3

    assert change_list_equals(
        processors["change-type-1"].changes, ct_1.changes + ct_2.changes + ct_3.changes
    )
    assert change_list_equals(processors["change-type-2"].changes, ct_2.changes)
    assert change_list_equals(processors["change-type-3"].changes, ct_3.changes)


def test_change_type_multi_level_inheritance():
    ct_1 = build_def_change_type("change-type-1", inherit=["change-type-2"])
    ct_2 = build_def_change_type("change-type-2", inherit=["change-type-3"])
    ct_3 = build_def_change_type("change-type-3")

    processors = init_change_type_processors([ct_1, ct_2, ct_3])
    assert len(processors) == 3

    assert change_list_equals(
        processors["change-type-1"].changes, ct_1.changes + ct_2.changes + ct_3.changes
    )
    assert change_list_equals(
        processors["change-type-2"].changes, ct_2.changes + ct_3.changes
    )
    assert change_list_equals(processors["change-type-3"].changes, ct_3.changes)


def test_change_type_multi_level_inheritance_multiple_paths():
    ct_1 = build_def_change_type(
        "change-type-1", inherit=["change-type-2", "change-type-3"]
    )
    ct_2 = build_def_change_type("change-type-2", inherit=["change-type-3"])
    ct_3 = build_def_change_type("change-type-3")

    processors = init_change_type_processors([ct_1, ct_2, ct_3])
    assert len(processors) == 3

    assert change_list_equals(
        processors["change-type-1"].changes, ct_1.changes + ct_2.changes + ct_3.changes
    )
    assert change_list_equals(
        processors["change-type-2"].changes, ct_2.changes + ct_3.changes
    )
    assert change_list_equals(processors["change-type-3"].changes, ct_3.changes)


# todo - write a test to check that the same change will not land
# multiple times in a changetype processor


def change_list_equals(
    a: Sequence[ChangeTypeChangeDetectorV1],
    b: Sequence[ChangeTypeChangeDetectorV1],
) -> bool:
    return len(a) == len(b) and all(a_item in b for a_item in a)
