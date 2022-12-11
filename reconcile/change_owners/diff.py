import copy
import json
import re
from collections.abc import MutableMapping
from dataclasses import dataclass
from enum import Enum
from functools import reduce
from typing import (
    Any,
    Optional,
)

import jsonpath_ng
import jsonpath_ng.ext
from deepdiff import DeepDiff
from deepdiff.helper import CannotCompare
from deepdiff.model import DiffLevel


class DiffType(Enum):
    ADDED = "added"
    REMOVED = "removed"
    CHANGED = "changed"


@dataclass
class Diff:
    """
    A change within a file, pinpointing the location of the change with a jsonpath.
    """

    path: jsonpath_ng.JSONPath
    diff_type: DiffType
    old: Optional[Any]
    new: Optional[Any]

    def create_subdiff(self, sub_path: jsonpath_ng.JSONPath) -> "Diff":
        if sub_path == self.path:
            # no need to subdiff ... this is the same path
            return self
        else:
            sub_path_str = str(sub_path)
            if self.path == jsonpath_ng.Root():
                absolute_sub_path = sub_path
            elif sub_path_str.startswith(self.path_str()):
                absolute_sub_path = jsonpath_ng.ext.parse(
                    f"${sub_path_str[len(self.path_str()):]}"
                )
            else:
                raise Exception(
                    f"sub_path {sub_path_str} is not prefixed by {self.path_str()}"
                )
            sub_old = absolute_sub_path.find(self.old)
            sub_new = absolute_sub_path.find(self.new)
            return Diff(
                path=sub_path,
                diff_type=self.diff_type,
                old=sub_old[0].value if len(sub_old) > 0 else None,
                new=sub_new[0].value if len(sub_new) > 0 else None,
            )

    def get_context_data_copy(self) -> Optional[Any]:
        if self.diff_type in [DiffType.ADDED, DiffType.CHANGED]:
            data_copy = copy.deepcopy(self.new)
        elif self.diff_type == DiffType.REMOVED:
            data_copy = copy.deepcopy(self.old)
        else:
            raise Exception(f"Unknown diff type {self.diff_type}")

        # remove file metadata
        if (
            data_copy
            and isinstance(data_copy, MutableMapping)
            and self.path == jsonpath_ng.Root()
        ):
            if SCHEMA_FIELD in data_copy:
                del data_copy[SCHEMA_FIELD]
            if PATH_FIELD in data_copy:
                del data_copy[PATH_FIELD]
            if SHA256SUM_FIELD_NAME in data_copy:
                del data_copy[SHA256SUM_FIELD_NAME]
        return data_copy

    def path_str(self) -> str:
        return str(self.path)

    def old_value_repr(self) -> Optional[str]:
        return self._value_repr(self.old)

    def new_value_repr(self) -> Optional[str]:
        return self._value_repr(self.new)

    def _value_repr(self, value: Optional[Any]) -> Optional[str]:
        if value:
            if isinstance(value, (dict, list)):
                return json.dumps(value, indent=2)
            else:
                return str(value)
        return value


IDENTIFIER_FIELD_NAME = "__identifier"
REF_FIELD_NAME = "$ref"


def _extract_identifier_from_object(obj: Any) -> Optional[str]:
    if isinstance(obj, dict):
        if IDENTIFIER_FIELD_NAME in obj:
            return obj.get(IDENTIFIER_FIELD_NAME)
        elif REF_FIELD_NAME in obj and len(obj) == 1:
            return obj.get(REF_FIELD_NAME)
    return None


def compare_object_ctx_identifier(
    x: Any, y: Any, level: Optional[DiffLevel] = None
) -> bool:
    """
    this function helps the deepdiff library to decide if two objects are
    actually the same in the sense of identity. this helps with finding
    changes in lists where reordering of items might occure.
    the __identifier key of an object is maintained by the qontract-validator
    based on the contextUnique flags on properties in jsonschemas of qontract-schema.

    in a list of heterogenous elements (e.g. openshiftResources), not every element
    necessarily has an __identitry property, e.g. vault-secret elements have one,
    but resource-template elements don't (because there is no set of properties
    clearly identifying the resulting resource). this is fine!

    if two objects have identities, they can be used to figure out if they are
    the same object.

    if only one of them has an identity, they are clearly not the same object.

    if two objects with no identity properties are compared, deepdiff will still
    try to figure out if they might be the same object based on a critical number
    of matching properties and values. this situation is signaled back to
    deepdiff by raising the CannotCompare exception.
    """
    x_id = _extract_identifier_from_object(x)
    y_id = _extract_identifier_from_object(y)
    if x_id and y_id:
        # if both have an identifier, they are the same if the identifiers are the same
        return x_id == y_id
    if x_id or y_id:
        # if only one of them has an identifier, they must be different objects
        return False
    # detecting if two objects without identifiers are the same, is beyond this
    # functions capability, hence it tells deepdiff to figure it out on its own
    raise CannotCompare() from None


SCHEMA_FIELD = "$schema"
PATH_FIELD = "path"
SHA256SUM_FIELD_NAME = "$file_sha256sum"
SHA256SUM_PATH = jsonpath_ng.parse(f"'{SHA256SUM_FIELD_NAME}'")


def extract_diffs(old_file_content: Any, new_file_content: Any) -> list[Diff]:
    diffs: list[Diff] = []
    if old_file_content and new_file_content:
        deep_diff = DeepDiff(
            old_file_content,
            new_file_content,
            ignore_order=True,
            iterable_compare_func=compare_object_ctx_identifier,
            cutoff_intersection_for_pairs=1,
        )

        # handle changed values
        diffs.extend(
            [
                Diff(
                    path=deepdiff_path_to_jsonpath(path),
                    diff_type=DiffType.CHANGED,
                    old=change.get("old_value"),
                    new=change.get("new_value"),
                )
                for path, change in deep_diff.get("values_changed", {}).items()
            ]
        )
        # handle property added
        for path in deep_diff.get("dictionary_item_added", []):
            jpath = deepdiff_path_to_jsonpath(path)
            change = jpath.find(new_file_content)
            change_value = change[0].value if change else None
            diffs.append(
                Diff(
                    path=jpath,
                    diff_type=DiffType.ADDED,
                    old=None,
                    new=change_value,
                )
            )
        # handle property removed
        for path in deep_diff.get("dictionary_item_removed", []):
            jpath = deepdiff_path_to_jsonpath(path)
            change = jpath.find(old_file_content)
            change_value = change[0].value if change else None
            diffs.append(
                Diff(
                    path=jpath,
                    diff_type=DiffType.REMOVED,
                    old=change_value,
                    new=None,
                )
            )
        # handle added items
        diffs.extend(
            [
                Diff(
                    path=deepdiff_path_to_jsonpath(path),
                    diff_type=DiffType.ADDED,
                    old=None,
                    new=change,
                )
                for path, change in deep_diff.get("iterable_item_added", {}).items()
            ]
        )
        # handle removed items
        diffs.extend(
            [
                Diff(
                    path=deepdiff_path_to_jsonpath(path),
                    diff_type=DiffType.REMOVED,
                    old=change,
                    new=None,
                )
                for path, change in deep_diff.get("iterable_item_removed", {}).items()
            ]
        )

        # if real changes have been detected, we are going to delete the
        # diff for the checksum field
        if len(diffs) > 1:
            diffs = [d for d in diffs if str(d.path) != SHA256SUM_FIELD_NAME]

    elif old_file_content:
        # file was deleted
        diffs.append(
            Diff(
                path=jsonpath_ng.Root(),
                diff_type=DiffType.REMOVED,
                old=old_file_content,
                new=None,
            )
        )
    elif new_file_content:
        # file was added
        diffs.append(
            Diff(
                path=jsonpath_ng.Root(),
                diff_type=DiffType.ADDED,
                old=None,
                new=new_file_content,
            )
        )

    return diffs


DEEP_DIFF_RE = re.compile(r"\['?(.*?)'?\]")


def deepdiff_path_to_jsonpath(deep_diff_path: str) -> jsonpath_ng.JSONPath:
    """
    deepdiff's way to describe a path within a data structure differs from jsonpath.
    This function translates deepdiff paths into regular jsonpath expressions.

    deepdiff paths start with "root" followed by a series of square bracket expressions
    fields and indices, e.g. `root['openshiftResources'][1]['version']`. The matching
    jsonpath expression is `openshiftResources.[1].version`
    """
    if not deep_diff_path.startswith("root"):
        raise ValueError("a deepdiff path must start with 'root'")

    def build_jsonpath_part(element: str) -> jsonpath_ng.JSONPath:
        if element.isdigit():
            return jsonpath_ng.Index(int(element))
        else:
            if "." in element:
                return jsonpath_ng.Fields(f"'{element}'")
            else:
                return jsonpath_ng.Fields(element)

    path_parts = [
        build_jsonpath_part(p) for p in DEEP_DIFF_RE.findall(deep_diff_path[4:])
    ]
    if path_parts:
        return reduce(lambda a, b: a.child(b), path_parts)
    else:
        return jsonpath_ng.Root()
