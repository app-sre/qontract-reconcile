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
K8S_ANNOTATION_LAC = "kubectl.kubernetes.io/last-applied-configuration"
NORMALIZE_IGNORE_ANNOTATIONS = QONTRACT_ANNOTATIONS | {K8S_ANNOTATION_LAC}


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

    annotations = n.body.get("metadata").get("annotations") or {}
    metadata["annotations"] = {
        k: v for k, v in annotations.items() if k not in NORMALIZE_IGNORE_ANNOTATIONS
    }

    # Run normalizers on Kinds with special needs
    NORMALIZERS.get(n.body["kind"], _normalize_noop)(n)
    return n


CPU_REGEX = re.compile(r"/.*/(requests|limits)/cpu$")
EMPTY_ENV_VALUE = re.compile(r"/.*/env/[0-9]+/value$")


def is_cpu_mutation(current: OR, desired: OR, patch: Mapping[str, Any]) -> bool:
    pointer = patch["path"]
    if re.match(CPU_REGEX, pointer):
        current_value = resolve_pointer(current.body, pointer)
        desired_value = patch["value"]
        return OR.cpu_equal(current_value, desired_value)

    return False


def is_empty_env_value(current: OR, desired: OR, patch: Mapping[str, Any]) -> bool:
    """Check if the patch is an empty env value. Empty values are removed in the
    current object

    :param current: Current object
    :param desired: Desired object
    :param patch: JSON patch
    :return: True if the change is not needed, False otherwise
    """
    pointer = patch["path"]
    return bool(
        patch["op"] == "add"
        and not patch["value"]
        and re.match(EMPTY_ENV_VALUE, pointer)
    )


def is_valid_change(current: OR, desired: OR, patch: Mapping[str, Any]) -> bool:
    # Only consider added or replaced values on the Desired object
    if patch["op"] not in {"add", "replace"}:
        return False

    # Check known mutations. Replaced values can happen if values have been
    # mutated by the API server
    if is_cpu_mutation(current, desired, patch):
        return False

    # Other cases
    return not is_empty_env_value(current, desired, patch)


def three_way_diff_using_hash(c_item: OR, d_item: OR) -> bool:
    c_item_sha256 = ""
    try:
        annotations = c_item.body["metadata"]["annotations"]
        c_item_sha256 = annotations["qontract.sha256sum"]
    except KeyError:
        logging.debug("Current object QR hash is missing -> Apply")
        return False

    if (
        c_item_integration := annotations["qontract.integration"]
    ) != d_item.integration:
        logging.info(
            f"resource switching integration from {c_item_integration} to {d_item.integration}"
        )
        return False

    # Original object does not match Desired -> Apply
    # Current object hash is not recalculated!
    if c_item_sha256 != d_item.sha256sum():
        logging.debug("Original and Desired objects hash differs -> Apply")
        return False

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
        logging.debug("Desired and Current objects differ -> Apply: %s", valid_changes)
        return False

    return True
