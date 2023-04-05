from collections.abc import (
    Callable,
    Iterable,
    Mapping,
)
from unittest.mock import (
    MagicMock,
    create_autospec,
)

import pytest

from reconcile.gql_definitions.saas_auto_promotions_manager.saas_files_for_auto_promotion import (
    SaasFileV2,
)
from reconcile.saas_auto_promotions_manager.utils.vcs import VCS
from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.state import State


@pytest.fixture
def saas_files_builder(
    gql_class_factory: Callable[[type[SaasFileV2], Mapping], SaasFileV2]
) -> Callable[[Iterable[Mapping]], list[SaasFileV2]]:
    def builder(data: Iterable[Mapping]) -> list[SaasFileV2]:
        return [gql_class_factory(SaasFileV2, d) for d in data]

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
def s3_state_builder() -> Callable[[Mapping], State]:
    def builder(data: Mapping) -> State:
        def get(key: str) -> dict:
            return data["get"][key]

        state = create_autospec(spec=State)
        state.get = get
        state.ls.side_effect = [data["ls"]]
        return state

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
