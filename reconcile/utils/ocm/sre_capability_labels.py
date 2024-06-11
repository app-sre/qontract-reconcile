from typing import Any

from pydantic import Field
from pydantic.fields import ModelField

from reconcile.utils.ocm.base import (
    LabelContainer,
    LabelSetTypeVar,
)
from reconcile.utils.ocm.labels import build_container_for_prefix


def sre_capability_label_key(
    sre_capability: str, config_atom: str | None = None
) -> str:
    """
    Generates label keys compliant with the naming schema defined in
    https://service.pages.redhat.com/dev-guidelines/docs/sre-capabilities/framework/ocm-labels/
    """
    if config_atom is None:
        return f"sre-capabilities.{sre_capability}"
    return f"sre-capabilities.{sre_capability}.{config_atom}"


def labelset_groupfield(group_prefix: str) -> Any:
    """
    Helper function to build the FieldMeta for a labelset field that groups labels.
    """
    return Field(group_by_prefix=group_prefix)


def build_labelset(
    labels: LabelContainer, dataclass: type[LabelSetTypeVar]
) -> LabelSetTypeVar:
    """
    Instantiates a dataclass from a set of labels.
    """
    raw_data = {
        field.alias: _labelset_field_value(labels, field)
        for field in dataclass.__fields__.values()
    }
    return dataclass(**raw_data)


def _labelset_field_value(labels: LabelContainer, field: ModelField) -> Any | None:
    key_prefix = field.field_info.extra.get("group_by_prefix")
    if key_prefix:
        return build_container_for_prefix(
            labels, key_prefix, strip_key_prefix=True
        ).get_values_dict()
    return labels.get_label_value(field.alias)
