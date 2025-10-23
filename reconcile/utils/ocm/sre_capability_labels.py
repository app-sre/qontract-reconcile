from typing import Any

from pydantic import WithJsonSchema
from pydantic.fields import FieldInfo

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


def labelset_groupfield(group_prefix: str) -> WithJsonSchema:
    """
    Helper function to build the FieldMeta for a labelset field that groups labels.
    """
    return WithJsonSchema({"group_by_prefix": group_prefix})


def build_labelset(
    labels: LabelContainer, dataclass: type[LabelSetTypeVar]
) -> LabelSetTypeVar:
    """
    Instantiates a dataclass from a set of labels.
    """
    raw_data = {
        field.alias or name: _labelset_field_value(labels, name, field)
        for name, field in dataclass.model_fields.items()
    }
    return dataclass(**raw_data)


def _labelset_field_value(
    labels: LabelContainer, name: str, field: FieldInfo
) -> Any | None:
    schema = next((m for m in field.metadata if isinstance(m, WithJsonSchema)), None)
    if (
        schema is None
        or not schema.json_schema
        or "group_by_prefix" not in schema.json_schema
    ):
        return labels.get_label_value(field.alias or name)

    return build_container_for_prefix(
        labels, schema.json_schema["group_by_prefix"], strip_key_prefix=True
    ).get_values_dict()
