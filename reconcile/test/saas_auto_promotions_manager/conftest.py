from collections.abc import (
    Callable,
    Iterable,
    Mapping,
    MutableMapping,
)
from unittest.mock import (
    MagicMock,
    create_autospec,
)

import pytest

from reconcile.gql_definitions.fragments.saas_target_namespace import (
    SaasTargetNamespace,
)
from reconcile.saas_auto_promotions_manager.utils.vcs import VCS
from reconcile.typed_queries.saas_files import SaasFile
from reconcile.utils.gitlab_api import GitLabApi


@pytest.fixture
def saas_files_builder(
    gql_class_factory: Callable[[type[SaasFile], Mapping], SaasFile]
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


@pytest.fixture
def vcs_builder() -> Callable[..., VCS]:
    def builder() -> VCS:
        vcs = create_autospec(spec=VCS)
        vcs.get_commit_sha.side_effect = ["new_sha"] * 100
        vcs._app_interface_api = MagicMock()
        return vcs

    return builder


@pytest.fixture
def gql_client_builder() -> Callable[..., GitLabApi]:
    def builder() -> GitLabApi:
        api = create_autospec(spec=GitLabApi)
        api.project = MagicMock()
        api.project.mergerequests = MagicMock()
        api.project.mergerequests.create.side_effect = []
        return api

    return builder


@pytest.fixture
def saas_target_namespace_builder(
    gql_class_factory: Callable[..., SaasTargetNamespace]
) -> Callable[..., SaasTargetNamespace]:
    def builder(data: MutableMapping) -> SaasTargetNamespace:
        if "environment" not in data:
            data["environment"] = {}
        if "app" not in data:
            data["app"] = {}
        if "cluster" not in data:
            data["cluster"] = {}
        return gql_class_factory(SaasTargetNamespace, data)

    return builder
