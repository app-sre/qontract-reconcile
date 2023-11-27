from collections.abc import (
    Callable,
    Iterable,
    Mapping,
)
from typing import (
    Any,
    TypeVar,
)
from urllib.parse import urljoin

import anymarkup
import requests

from reconcile.utils.exceptions import FetchResourceError
from reconcile.utils.gql import GqlGetResourceError


def prom_get(
    url: str,
    params: Mapping[Any, Any] | None = None,
    token: str | None = None,
    ssl_verify: bool = True,
    uri: str = "api/v1/query",
    timeout: int = 60,
) -> list[dict[str, str]]:
    url = urljoin(url, uri)
    headers = {"accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    response = requests.get(
        url, params=params, headers=headers, verify=ssl_verify, timeout=timeout
    )
    response.raise_for_status()
    return [r["metric"] for r in response.json()["data"]["result"]]


Key = TypeVar("Key")
T = TypeVar("T")


def uniquify(key: Callable[[T], Key], items: Iterable[T]) -> list[T]:
    return list({key(item): item for item in items}.values())


def get_values(gql_get_resource_func: Callable, path: str) -> dict[str, Any]:
    try:
        raw_values = gql_get_resource_func(path)
    except GqlGetResourceError as e:
        raise FetchResourceError(str(e))
    try:
        values = anymarkup.parse(raw_values["content"], force_types=None)
        values.pop("$schema", None)
    except anymarkup.AnyMarkupError:
        e_msg = "Could not parse data. Skipping resource: {}"
        raise FetchResourceError(e_msg.format(path))
    return values


def override_values(values: Mapping, overrides: Mapping | None) -> dict:
    if overrides is None:
        return {**values}
    return {**values, **overrides}
