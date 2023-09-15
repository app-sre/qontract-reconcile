import base64
import logging
import re
from collections.abc import Mapping
from typing import Any

import jsonpatch  # type: ignore
from jsonpointer import resolve_pointer  # type: ignore

from reconcile.utils.openshift_resource import QONTRACT_ANNOTATIONS
from reconcile.utils.openshift_resource import OpenshiftResource as OR

NORMALIZE_COMPARE_EXCLUDED_ATTRS = {
    "creationTimestamp",
    "resourceVersion",
    "generation",
    "selfLink",
    "uid",
    "fieldRef",
    "managedFields",
    "namespace",
}


def _normalize_secret(secret: OR) -> None:
    body = secret.body
    string_data = body.get("stringData")

    if string_data:
        data = body.get("data") or {}
        body["data"] = data | {
            k: base64.b64encode(str(v).encode()).decode("utf-8")
            for k, v in string_data.items()
        }
        secret.body = {k: v for k, v in body.items() if k != "stringData"}


def _normalize_noop(item: OR) -> None:
    pass


NORMALIZERS = {"Secret": _normalize_secret}


def normalize_object(item: OR) -> OR:
    # Remove K8s managed attributes not needed to compare objects
    metadata = {
        k: v
        for k, v in item.body["metadata"].items()
        if k not in NORMALIZE_COMPARE_EXCLUDED_ATTRS
    }

    n = OR(
        body=item.body | {"metadata": metadata},
        integration=item.integration,
        integration_version=item.integration_version,
        error_details=item.error_details,
        caller_name=item.caller_name,
        validate_k8s_object=False,
    )

    annotations = n.body.get("annotations", {})
    metadata["annotations"] = {
        k: v for k, v in annotations.items() if k not in QONTRACT_ANNOTATIONS
    }

    # Run normalizers on Kinds with special needs
    NORMALIZERS.get(n.body["kind"], _normalize_noop)(n)
    return n


CPU_REGEX = re.compile(r"/.*/(requests|limits)/cpu$")


def is_cpu_mutation(current: OR, desired: OR, patch: Mapping[str, Any]) -> bool:
    pointer = patch["path"]
    if re.match(CPU_REGEX, pointer):
        current_value = resolve_pointer(current.body, pointer)
        desired_value = patch["value"]
        return OR.cpu_equal(current_value, desired_value)

    return False


def is_valid_change(current: OR, desired: OR, patch: Mapping[str, Any]) -> bool:
    # Only consider added or replaced values on the Desired object
    if patch["op"] not in ["add", "replace"]:
        return False

    # Check known mutations. Replaced values can happen if values have been
    # mutated by the API server
    if is_cpu_mutation(current, desired, patch):
        return False

    return True


def three_way_diff_using_hash(c_item: OR, d_item: OR) -> bool:
    # Get the ORIGINAL object hash
    # This needs to be improved in OR, by now is just a PoC
    c_item_sha256 = ""
    try:
        annotations = c_item.body["metadata"]["annotations"]
        c_item_sha256 = annotations["qontract.sha256sum"]
    except KeyError:
        logging.info("Current object QR hash is missing -> Apply")
        return False

    # Original object does not match Desired -> Apply
    # Current object is not recalculated!
    # d_item_sha256 = OR.calculate_sha256sum(OR.serialize(d_item.body))
    # if c_item_sha256 != d_item_sha256:
    if c_item_sha256 != d_item.sha256sum():
        logging.info("Original and Desired objects hash differs -> Apply")
        return False

    # If there are differences between current and desired -> Apply
    # The patch only detects changes with attributes defined in the desired state.
    # Values in the current state added by operators or other actors are not taken
    # into account

    current = normalize_object(c_item)
    desired = normalize_object(d_item)

    patch = jsonpatch.JsonPatch.from_diff(current.body, desired.body)
    valid_changes = [
        item for item in patch.patch if is_valid_change(current, desired, item)
    ]
    if len(valid_changes) > 0:
        logging.info("Desired and Current objects differ -> Apply")
        logging.info(valid_changes)
        return False

    return True
