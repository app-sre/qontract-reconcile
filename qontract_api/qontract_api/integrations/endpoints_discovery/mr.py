"""Merge request rendering, parsing and hashing for endpoints-discovery.

Everything here is pure: strings and models in, strings out. The hash and
description formats are byte-compatible with the legacy integration, because
an open merge request created before the migration carries a hash that the
new implementation must recognise as current.
"""

from __future__ import annotations

import hashlib
import operator
import re
import string
from io import StringIO
from typing import TYPE_CHECKING, Any

import jinja2
from jinja2.sandbox import SandboxedEnvironment
from pydantic import BaseModel
from qontract_utils.json_utils import json_dumps
from qontract_utils.ruamel import create_ruamel_instance

if TYPE_CHECKING:
    from collections.abc import Sequence

    from qontract_api.integrations.endpoints_discovery.domain import (
        AppEndpointPlan,
        RouteLike,
    )

INTEGRATION = "endpoints-discovery"
VERSION = "1.0.0"
LABEL = "ENDPOINTS-DISCOVERY"

INTEGRATION_REF = "integration"
VERSION_REF = "endpoints-discover-version"
HASH_REF = "hash"

DATA_SEPARATOR = "**DO NOT MANUALLY CHANGE ANYTHING BELOW THIS LINE**"

# The separator must appear exactly once: before and after it.
_EXPECTED_DESCRIPTION_PARTS = 2

TITLE = "[auto] endpoints-discovery: update application endpoints"

_COMPILED_REGEXES = {
    ref: re.compile(rf".*{ref}: (.*)$", re.MULTILINE)
    for ref in (INTEGRATION_REF, VERSION_REF, HASH_REF)
}

_DESCRIPTION = string.Template(
    f"""
This MR is triggered by app-interface's [endpoints-discovery](https://github.com/app-sre/qontract-reconcile/tree/master/reconcile/endpoints_discovery).

Please **do not remove the `{LABEL}` label** from this MR!

Parts of this description are used to manage the MR.

{DATA_SEPARATOR}

* {INTEGRATION_REF}: {INTEGRATION}
* {VERSION_REF}: {VERSION}
* {HASH_REF}: $hash
"""
)


class MergeRequestMetadata(BaseModel, frozen=True):
    """Machine-readable data embedded below the description separator."""

    integration: str
    version: str
    hash: str


def endpoint_prefix(cluster_name: str, namespace_name: str) -> str:
    """Return the prefix identifying discovered endpoints for a namespace."""
    return f"{INTEGRATION}/{cluster_name}/{namespace_name}/"


def compile_endpoint_name(prefix: str, route_name: str) -> str:
    """Compose an endpoint name from its namespace prefix and route name."""
    return f"{prefix}{route_name}"


def parse_endpoint_name(endpoint_name: str) -> tuple[str, str, list[str]]:
    """Split a discovered endpoint name into cluster, namespace and route names.

    Raises:
        ValueError: If the name is not a discovered endpoint for this integration
    """
    integration_name, cluster, namespace, route_names = endpoint_name.split("/")
    if integration_name != INTEGRATION:
        raise ValueError("Invalid integration name")
    return cluster, namespace, route_names.split("|")


def render_template(
    template: str, endpoint_name: str, route: RouteLike
) -> dict[str, Any]:
    """Render the App-Interface endpoint template into a mapping.

    A sandboxed environment is used because the template is untrusted input
    from App-Interface; it only ever needs `endpoint_name` and `route.url`.
    """
    env = SandboxedEnvironment(
        undefined=jinja2.StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    rendered = env.from_string(template).render({
        "endpoint_name": endpoint_name,
        "route": route,
    })
    return create_ruamel_instance().load(rendered)


def render_merge_request_content(
    current_content: str,
    endpoints_to_add: list[dict[str, Any]],
    endpoints_to_change: dict[str, dict[str, Any]],
    endpoints_to_delete: list[str],
) -> str:
    """Update the `endPoints` list of an application file.

    Existing order is preserved, changed entries are replaced in place,
    untouched entries are carried over verbatim, and additions are appended.
    """
    yml = create_ruamel_instance(explicit_start=True)
    content = yml.load(current_content)
    new_endpoints = []
    for app_endpoint in content.setdefault("endPoints", []):
        if app_endpoint["name"] in endpoints_to_delete:
            continue
        if app_endpoint["name"] in endpoints_to_change:
            new_endpoints.append(endpoints_to_change[app_endpoint["name"]])
        else:
            new_endpoints.append(app_endpoint)

    new_endpoints.extend(endpoints_to_add)
    content["endPoints"] = new_endpoints
    with StringIO() as stream:
        yml.dump(content, stream)
        return stream.getvalue()


def endpoint_hash(name: str, data: dict[str, Any]) -> str:
    """Hash an endpoint exactly as the legacy `Endpoint.hash` did."""
    return hashlib.sha256(json_dumps({"name": name, "data": data}).encode()).hexdigest()


def app_hash(
    path: str,
    endpoints_to_add: Sequence[AppEndpointPlan],
    endpoints_to_change: Sequence[AppEndpointPlan],
    endpoints_to_delete: Sequence[AppEndpointPlan],
) -> str:
    """Hash an application's plan exactly as the legacy `App.hash` did.

    The literal's whitespace is significant: it is part of the hashed string.
    """
    return hashlib.sha256(
        f"""
                {path}
                {[endpoint_hash(i.name, i.data) for i in sorted(endpoints_to_add, key=lambda i: i.name)]}
                {[endpoint_hash(i.name, i.data) for i in sorted(endpoints_to_change, key=lambda i: i.name)]}
                {[endpoint_hash(i.name, i.data) for i in sorted(endpoints_to_delete, key=lambda i: i.name)]}
            """.encode()
    ).hexdigest()


def hash_apps(apps: Sequence[tuple[str, str]]) -> str:
    """Hash the aggregate plan from (app name, app hash) pairs.

    Sorting by application name makes the result independent of payload order.
    """
    return hashlib.sha256(
        ",".join(
            app_hash for _, app_hash in sorted(apps, key=operator.itemgetter(0))
        ).encode()
    ).hexdigest()


def render_title() -> str:
    """Return the merge request title."""
    return TITLE


def render_description(plan_hash: str) -> str:
    """Render the merge request description for a given plan hash."""
    return _DESCRIPTION.safe_substitute({"hash": plan_hash, "integration": INTEGRATION})


def parse_merge_request_description(description: str) -> MergeRequestMetadata | None:
    """Extract the machine-readable metadata, or None if it is missing.

    A None result means the MR was not rendered by this integration (or was
    hand-edited below the separator), which callers treat as invalid.
    """
    parts = description.split(DATA_SEPARATOR)
    if len(parts) != _EXPECTED_DESCRIPTION_PARTS:
        return None

    values: dict[str, str] = {}
    for ref, pattern in _COMPILED_REGEXES.items():
        match = pattern.search(parts[1])
        if match is None:
            return None
        values[ref] = match.group(1)

    return MergeRequestMetadata(
        integration=values[INTEGRATION_REF],
        version=values[VERSION_REF],
        hash=values[HASH_REF],
    )
