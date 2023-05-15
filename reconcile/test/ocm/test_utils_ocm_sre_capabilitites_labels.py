import pytest
from pydantic import (
    BaseModel,
    Field,
)

from reconcile.test.ocm.fixtures import build_label
from reconcile.utils.models import CSV
from reconcile.utils.ocm.labels import (
    LabelContainer,
    build_label_container,
)
from reconcile.utils.ocm.sre_capability_labels import (
    build_labelset,
    labelset_groupfield,
    sre_capability_label_key,
)


def test_build_sre_capability_label_key() -> None:
    assert (
        sre_capability_label_key("my_capability", "option")
        == "sre-capabilities.my_capability.option"
    )


@pytest.fixture
def label_container() -> LabelContainer:
    return build_label_container(
        [
            build_label(sre_capability_label_key("c", "str_label"), "str"),
            build_label(sre_capability_label_key("c", "int_label"), "5"),
            build_label(sre_capability_label_key("c", "bool_label"), "true"),
            build_label(sre_capability_label_key("c", "csv_label"), "a,b,c"),
            build_label(sre_capability_label_key("c", "group.a"), "a"),
            build_label(sre_capability_label_key("c", "group.b"), "b"),
            build_label(sre_capability_label_key("c", "group.c"), "c"),
        ]
    )


class SimpleLabelSet(BaseModel):
    str_option: str = Field(alias=sre_capability_label_key("c", "str_label"))
    int_option: int = Field(alias=sre_capability_label_key("c", "int_label"))
    bool_option: bool = Field(alias=sre_capability_label_key("c", "bool_label"))


def test_build_simple_labelset(label_container: LabelContainer) -> None:
    labelset = build_labelset(label_container, SimpleLabelSet)
    assert labelset.str_option == "str"
    assert labelset.int_option == 5
    assert labelset.bool_option is True


class CSVLabelSet(BaseModel):
    list_option: CSV = Field(alias=sre_capability_label_key("c", "csv_label"))


def test_build_csv_labelset(label_container: LabelContainer) -> None:
    labelset = build_labelset(label_container, CSVLabelSet)
    assert labelset.list_option == ["a", "b", "c"]


class GroupingLabelSet(BaseModel):
    group: dict[str, str] = labelset_groupfield(
        group_prefix=sre_capability_label_key("c", "group.")
    )


def test_build_grouping_labelset(label_container: LabelContainer) -> None:
    labelset = build_labelset(label_container, GroupingLabelSet)
    assert labelset.group == {"a": "a", "b": "b", "c": "c"}
