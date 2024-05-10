from collections.abc import Callable, Iterable, Mapping, MutableMapping
from typing import Any
from unittest.mock import create_autospec

import pytest

from reconcile.typed_queries.saas_files import SaasFile
from reconcile.utils.vcs import VCS


@pytest.fixture
def vcs_builder() -> Callable[[Mapping], VCS]:
    def builder(data: Mapping) -> VCS:
        def _mocked_commits_between(*args: Any, **kwargs: Any) -> list:
            commit_from = kwargs["commit_from"]
            commit_to = kwargs["commit_to"]
            key = f"{commit_from}/{commit_to}"
            if data[key] == 0:
                return []
            return [1] * data[key]

        vcs = create_autospec(spec=VCS)
        vcs.get_commits_between = _mocked_commits_between
        return vcs

    return builder


@pytest.fixture
def saas_files_builder(
    gql_class_factory: Callable[[type[SaasFile], Mapping], SaasFile],
) -> Callable[[Iterable[MutableMapping]], list[SaasFile]]:
    def builder(data: Iterable[MutableMapping]) -> list[SaasFile]:
        for d in data:
            if "app" not in d:
                d["app"] = {}
            if "pipelinesProvider" not in d:
                d["pipelinesProvider"] = {}
            if "managedResourceTypes" not in d:
                d["managedResourceTypes"] = []
            if "imagePatterns" not in d:
                d["imagePatterns"] = []
            for rt in d.get("resourceTemplates", []):
                for t in rt.get("targets", []):
                    ns = t["namespace"]
                    if "name" not in ns:
                        ns["name"] = "some_name"
                    if "environment" not in ns:
                        ns["environment"] = {}
                    if "app" not in ns:
                        ns["app"] = {}
                    if "cluster" not in ns:
                        ns["cluster"] = {}
        return [gql_class_factory(SaasFile, d) for d in data]

    return builder
