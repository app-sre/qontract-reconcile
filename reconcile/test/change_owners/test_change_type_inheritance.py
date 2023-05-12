from collections.abc import Sequence
from typing import (
    Any,
    Optional,
)

import pytest

from reconcile.change_owners.bundle import BundleFileType
from reconcile.change_owners.change_types import (
    ChangeDetector,
    ChangeTypeCycleError,
    ChangeTypeIncompatibleInheritanceError,
    ChangeTypePriority,
    JsonPathChangeDetector,
    init_change_type_processors,
)
from reconcile.gql_definitions.change_owners.queries.change_types import (
    ChangeTypeChangeDetectorJsonPathProviderV1,
    ChangeTypeChangeDetectorV1,
    ChangeTypeV1,
    ChangeTypeV1_ChangeTypeV1,
)
from reconcile.test.change_owners.fixtures import (
    MockFileDiffResolver,
    build_jsonpath_change,
)


def build_def_change_type(
    name: str, inherit: Optional[list[str]] = None
) -> ChangeTypeV1:
    return ChangeTypeV1(
        name=name,
        description=name,
        contextType=BundleFileType.DATAFILE.value,
        contextSchema="context-schema",
        disabled=False,
        priority=ChangeTypePriority.HIGH.value,
        changes=[
            build_jsonpath_change(
                schema=f"/schema/change-schema-{name}",
                selectors=[f"selector.{name}"],
            )
        ],
        inherit=[ChangeTypeV1_ChangeTypeV1(name=i) for i in inherit or []],
        implicitOwnership=[],
    )


def test_change_type_no_inheritance() -> None:
    ct_1 = build_def_change_type("change-type-1")
    ct_2 = build_def_change_type("change-type-2")

    processors = init_change_type_processors(
        [ct_1, ct_2],
        MockFileDiffResolver(fail_on_unknown_path=False),
    )
    assert len(processors) == 2


def test_change_type_inheritance_cycle() -> None:
    ct_1 = build_def_change_type("change-type-1", inherit=["change-type-2"])
    ct_2 = build_def_change_type("change-type-2", inherit=["change-type-3"])
    ct_3 = build_def_change_type("change-type-3", inherit=["change-type-1"])

    with pytest.raises(ChangeTypeCycleError) as e:
        init_change_type_processors(
            [ct_1, ct_2, ct_3],
            MockFileDiffResolver(fail_on_unknown_path=False),
        )
    assert e.value.args[0] == "Cycles detected in change-type inheritance"
    assert set(e.value.args[1][0]) == {ct_1.name, ct_2.name, ct_3.name}


def test_change_type_inheritance_context_schema_mismatch() -> None:
    """
    a mismatch in context schema in an inheritance chain should be detected
    """
    ct_1 = build_def_change_type("change-type-1", inherit=["change-type-2"])
    ct_1.context_schema = "schema-1"
    ct_2 = build_def_change_type("change-type-2")
    ct_2.context_schema = "schema-2"

    with pytest.raises(ChangeTypeIncompatibleInheritanceError):
        init_change_type_processors(
            [ct_1, ct_2],
            MockFileDiffResolver(fail_on_unknown_path=False),
        )


def test_change_type_inhertiance_no_context_schema() -> None:
    """
    missing context schema is ok as long as both change types
    in an inheritance chain miss it
    """
    ct_1 = build_def_change_type("change-type-1", inherit=["change-type-2"])
    ct_1.context_schema = None
    ct_2 = build_def_change_type("change-type-2")
    ct_2.context_schema = None

    init_change_type_processors(
        [ct_1, ct_2],
        MockFileDiffResolver(fail_on_unknown_path=False),
    )


def test_change_type_inheritance_context_type_mismatch() -> None:
    """
    all change types in an inheritance chain must have the same context type
    """
    ct_1 = build_def_change_type("change-type-1", inherit=["change-type-2"])
    ct_2 = build_def_change_type("change-type-2")
    ct_2.context_type = BundleFileType.RESOURCEFILE.value

    with pytest.raises(ChangeTypeIncompatibleInheritanceError):
        init_change_type_processors(
            [ct_1, ct_2],
            MockFileDiffResolver(fail_on_unknown_path=False),
        )


def test_change_type_single_level_inheritance() -> None:
    ct_1 = build_def_change_type(
        "change-type-1", inherit=["change-type-2", "change-type-3"]
    )
    ct_2 = build_def_change_type("change-type-2")
    ct_3 = build_def_change_type("change-type-3")

    processors = init_change_type_processors(
        [ct_1, ct_2, ct_3],
        MockFileDiffResolver(fail_on_unknown_path=False),
    )
    assert len(processors) == 3

    assert change_list_equals(
        processors["change-type-1"].change_detectors,
        ct_1.changes + ct_2.changes + ct_3.changes,
    )
    assert change_list_equals(
        processors["change-type-2"].change_detectors, ct_2.changes
    )
    assert change_list_equals(
        processors["change-type-3"].change_detectors, ct_3.changes
    )


def test_change_type_multi_level_inheritance() -> None:
    ct_1 = build_def_change_type("change-type-1", inherit=["change-type-2"])
    ct_2 = build_def_change_type("change-type-2", inherit=["change-type-3"])
    ct_3 = build_def_change_type("change-type-3")

    processors = init_change_type_processors(
        [ct_1, ct_2, ct_3],
        MockFileDiffResolver(fail_on_unknown_path=False),
    )
    assert len(processors) == 3

    assert change_list_equals(
        processors["change-type-1"].change_detectors,
        ct_1.changes + ct_2.changes + ct_3.changes,
    )
    assert change_list_equals(
        processors["change-type-2"].change_detectors, ct_2.changes + ct_3.changes
    )
    assert change_list_equals(
        processors["change-type-3"].change_detectors, ct_3.changes
    )


def test_change_type_multi_level_inheritance_multiple_paths() -> None:
    ct_1 = build_def_change_type(
        "change-type-1", inherit=["change-type-2", "change-type-3"]
    )
    ct_2 = build_def_change_type("change-type-2", inherit=["change-type-3"])
    ct_3 = build_def_change_type("change-type-3")

    processors = init_change_type_processors(
        [ct_1, ct_2, ct_3],
        MockFileDiffResolver(fail_on_unknown_path=False),
    )
    assert len(processors) == 3

    assert change_list_equals(
        processors["change-type-1"].change_detectors,
        ct_1.changes + ct_2.changes + ct_3.changes,
    )
    assert change_list_equals(
        processors["change-type-2"].change_detectors, ct_2.changes + ct_3.changes
    )
    assert change_list_equals(
        processors["change-type-3"].change_detectors, ct_3.changes
    )


# todo - write a test to check that the same change will not land
# multiple times in a changetype processor


def change_list_equals(
    a: Sequence[ChangeDetector],
    b: Sequence[ChangeTypeChangeDetectorV1],
) -> bool:
    def detector_to_tuple(d: ChangeDetector) -> Any:
        if isinstance(d, JsonPathChangeDetector):
            return (d.change_schema, d.json_path_selectors)
        else:
            raise ValueError(f"unknown change detector type: {type(d)}")

    def change_to_tuple(c: ChangeTypeChangeDetectorV1) -> Any:
        if isinstance(c, ChangeTypeChangeDetectorJsonPathProviderV1):
            return (c.change_schema, c.json_path_selectors)
        else:
            raise ValueError(f"unknown change type change: {type(c)}")

    a = [detector_to_tuple(d) for d in a]
    b = [change_to_tuple(d) for d in b]
    return len(a) == len(b) and all(a_item in b for a_item in a)
