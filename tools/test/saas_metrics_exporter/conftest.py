from collections.abc import Callable, Iterable, Mapping, MutableMapping

import pytest

from reconcile.typed_queries.saas_files import SaasFile


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
