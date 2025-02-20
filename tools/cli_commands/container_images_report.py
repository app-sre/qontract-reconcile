import re
from collections import defaultdict
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel
from sretoolbox.utils import threaded

from reconcile.gql_definitions.common.namespaces import NamespaceV1
from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.typed_queries.namespaces import get_namespaces
from reconcile.utils.oc_filters import filter_namespaces_by_cluster_and_namespace
from reconcile.utils.oc_map import OCMap, init_oc_map_from_namespaces
from reconcile.utils.secret_reader import create_secret_reader

IMAGE_NAME_REGEX = re.compile(
    r"^(?P<name>[a-zA-Z0-9][a-zA-Z0-9/_.-]+)(?:$|(?:@sha256)?:.+.$)"
)


class NamespaceImages(BaseModel):
    namespace_name: str
    app_name: str
    image_names: list[str] | None = None
    error_message: str | None = None


def get_all_pods_images(
    cluster_name: Sequence[str] | None = None,
    namespace_name: Sequence[str] | None = None,
    thread_pool_size: int = 10,
    use_jump_host: bool = True,
    include_pattern: str | None = None,
    exclude_pattern: str | None = None,
) -> list[dict[str, Any]]:
    """Gets all the images in the clusters/namespaces given. Returns a list of dicts
    with the following keys:
      * name: image name
      * namespaces:  a comma separated list of namespaces where the instance is used
      * count: number of uses of the image
    """
    all_namespaces = get_namespaces()
    namespaces = filter_namespaces_by_cluster_and_namespace(
        namespaces=all_namespaces,
        cluster_names=cluster_name,
        namespace_names=namespace_name,
    )
    vault_settings = get_app_interface_vault_settings()
    secret_reader = create_secret_reader(use_vault=vault_settings.vault)
    oc_map = init_oc_map_from_namespaces(
        namespaces=namespaces,
        integration="qontract-cli-get-namespace_images",
        secret_reader=secret_reader,
        use_jump_host=use_jump_host,
        thread_pool_size=thread_pool_size,
        init_projects=True,
    )

    return fetch_pods_images_from_namespaces(
        namespaces=namespaces,
        oc_map=oc_map,
        exclude_pattern=exclude_pattern,
        include_pattern=include_pattern,
        thread_pool_size=thread_pool_size,
    )


def fetch_pods_images_from_namespaces(
    namespaces: list[NamespaceV1],
    oc_map: OCMap,
    include_pattern: str | None = None,
    exclude_pattern: str | None = None,
    thread_pool_size: int = 10,
) -> list[dict[str, Any]]:
    all_namespace_images = threaded.run(
        func=_get_namespace_images,
        iterable=namespaces,
        thread_pool_size=thread_pool_size,
        oc_map=oc_map,
    )

    errors: defaultdict = defaultdict(int)
    result: defaultdict = defaultdict(_get_all_images_default)
    for ni in all_namespace_images:
        if ni.error_message:
            errors[f"{ni.namespace_name}/{ni.error_message}"] += 1
            continue

        for name in ni.image_names or []:
            result[name]["namespaces"].add(ni.namespace_name)
            result[name]["apps"].add(ni.app_name)
            result[name]["count"] += 1

    exclude_pattern_compiled: re.Pattern | None = None
    if exclude_pattern:
        exclude_pattern_compiled = re.compile(exclude_pattern)

    include_pattern_compiled: re.Pattern | None = None
    if include_pattern:
        include_pattern_compiled = re.compile(include_pattern)

    result_filtered_flattened: list[dict[str, Any]] = []
    for name, value in sorted(result.items()):
        if include_pattern_compiled and not include_pattern_compiled.match(name):
            continue
        if exclude_pattern_compiled and exclude_pattern_compiled.match(name):
            continue

        result_filtered_flattened.append({
            "name": name,
            "namespaces": ",".join(sorted(value["namespaces"])),
            "apps": ",".join(sorted(value["apps"])),
            "count": value["count"],
        })

    # append errors if they exist in the filtered result
    # not very canonical, but it is better than ignoring them
    if errors:
        for message, count in sorted(errors.items()):
            result_filtered_flattened.append({
                "name": "error",
                "namespaces": message,
                "apps": "",
                "count": count,
            })

    return result_filtered_flattened


def _get_all_images_default() -> dict[str, Any]:
    return {"namespaces": set(), "apps": set(), "count": 0}


def _get_namespace_images(ns: NamespaceV1, oc_map: OCMap) -> NamespaceImages:
    image_names = []

    try:
        oc = oc_map.get_cluster(ns.cluster.name)
        pod_items = oc.get_items("Pod", namespace=ns.name)
        for pod in pod_items:
            containers = pod.get("spec", {}).get("containers", [])
            containers.extend(pod.get("spec", {}).get("initContainers", []))

            for c in containers:
                if m := IMAGE_NAME_REGEX.match(c["image"]):
                    image_names.append(m.group("name"))  # noqa: PERF401
    except Exception as exc:
        return NamespaceImages(
            namespace_name=ns.name,
            app_name=ns.app.name,
            error_message=str(exc),
        )

    return NamespaceImages(
        namespace_name=ns.name,
        app_name=ns.app.name,
        image_names=image_names,
    )
