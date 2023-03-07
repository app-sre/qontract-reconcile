from collections.abc import Iterable
from typing import (
    Any,
    Optional,
)

from reconcile.gql_definitions.fragments.vault_secret import VaultSecret
from reconcile.gql_definitions.statuspage.statuspages import (
    AppV1,
    ManualStatusProviderConfigV1,
    ManualStatusProviderV1,
    StatusPageComponentV1,
    StatusPageV1,
)
from reconcile.statuspage.atlassian import (
    AtlassianAPI,
    AtlassianRawComponent,
    AtlassianStatusPageProvider,
)
from reconcile.statuspage.state import ComponentBindingState


def describe_component_v1(
    name: str, display_name: str, group: Optional[str], status: Optional[str]
) -> tuple[str, str, Optional[str], Optional[str]]:
    return (name, display_name, group, status)


def construct_status_page_v1(
    name: str,
    provider: str,
    component_repr: list[tuple[str, str, Optional[str], Optional[str]]],
) -> StatusPageV1:
    components = [
        StatusPageComponentV1(
            name=name,
            displayName=display_name,
            description=display_name,
            app=AppV1(
                name=f"app-{name}",
            ),
            path=f"/path/{name}.yml",
            status_config=[
                ManualStatusProviderV1(
                    provider="manual",
                    manual=ManualStatusProviderConfigV1(
                        **{"componentStatus": status, "from": None, "until": None}  # type: ignore[arg-type]
                    ),
                )
            ]
            if status
            else [],
            groupName=group_name,
        )
        for name, display_name, group_name, status in component_repr
    ]
    return StatusPageV1(
        name=name,
        apiUrl="https://api.page.com",
        pageId=name,
        provider=provider,
        credentials=VaultSecret(
            field="field",
            path="path",
            version=None,
            format=None,
        ),
        components=components,
    )


class MockAtlassianAPI:
    def __init__(self, components: list[AtlassianRawComponent]):
        self.components = components

    def list_components(self) -> list[AtlassianRawComponent]:
        return self.components

    def update_component(self, id: str, data: dict[str, Any]) -> None:
        pass

    def create_component(self, data: dict[str, Any]) -> str:
        return "id"  # todo make better

    def delete_component(self, id: str) -> None:
        return None


class DictComponentBindingState:
    def __init__(self, name_to_id: dict[str, str]):
        self.name_to_id_cache = name_to_id
        self._build_id_to_name_cache()

    def _build_id_to_name_cache(self):
        self.id_to_name_cache: dict[str, str] = {
            v: k for k, v in self.name_to_id_cache.items()
        }

    def get_id_for_component_name(self, component_name: str) -> Optional[str]:
        return self.name_to_id_cache.get(component_name)

    def get_name_for_component_id(self, component_id: str) -> Optional[str]:
        return self.id_to_name_cache.get(component_id)

    def bind_component(self, component_name: str, component_id: str):
        self.name_to_id_cache[component_name] = component_id
        self.id_to_name_cache[component_id] = component_name

    def forget_component(self, component_name: str):
        del self.name_to_id_cache[component_name]
        self._build_id_to_name_cache()


def describe_atlassian_component(
    id: str, name: str, group: Optional[str], status: str, binding: Optional[str]
) -> tuple[str, str, Optional[str], str, Optional[str]]:
    return (id, name, group, status, binding)


def construct_binding_state(
    component_repr: Iterable[tuple[str, str, Optional[str], str, Optional[str]]]
) -> ComponentBindingState:
    return DictComponentBindingState(
        {
            bound_to_component: id
            for id, _, _, _, bound_to_component in component_repr
            if bound_to_component
        }
    )


def construct_atlassian_api(
    component_repr: Iterable[tuple[str, str, Optional[str], str, Optional[str]]],
    group_names: Iterable[str],
) -> AtlassianAPI:
    components = [
        AtlassianRawComponent(
            id=id,
            name=name,
            description=name,
            position=idx,
            status=status,
            automation_email=None,
            group_id=f"{group_name}-id" if group_name else None,
            group=False,
        )
        for idx, (id, name, group_name, status, _) in enumerate(component_repr)
    ]
    groups = [
        AtlassianRawComponent(
            id=f"{group_name}-id",
            name=group_name,
            description=group_name,
            position=idx,
            status="operational",
            automation_email=None,
            group_id=None,
            group=True,
        )
        for idx, group_name in enumerate(group_names)
    ]
    return MockAtlassianAPI(
        components=components + groups,
    )


def construct_atlassian_page(
    page_name: str,
    component_repr: Iterable[tuple[str, str, Optional[str], str, Optional[str]]],
    groups: Iterable[str],
) -> AtlassianStatusPageProvider:
    api = construct_atlassian_api(component_repr, groups)
    return AtlassianStatusPageProvider(
        page_name=page_name,
        api=api,
        component_binding_state=construct_binding_state(component_repr),
    )
