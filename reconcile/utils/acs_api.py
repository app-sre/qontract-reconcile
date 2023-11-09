from typing import (
    Any,
    Optional,
    Self,
)

import requests
from pydantic import BaseModel


class Role(BaseModel):
    name: str
    permission_set_id: str
    access_scope_id: str
    description: str
    system_default: bool

    def __init__(self, api_data: Any) -> None:
        # attributes defined within stackrox(ACS) API for GET /v1/roles
        check_len_attributes(
            ["name", "permissionSetId", "accessScopeId"],
            api_data,
        )

        # traits is populated for system default resources and contains `origin: DEFAULT`
        # this attribute is used to ignore such resources from reconciliation
        traits = api_data.get("traits")
        is_default = traits is not None and traits.get("origin") == "DEFAULT"

        super().__init__(
            name=api_data["name"],
            permission_set_id=api_data["permissionSetId"],
            access_scope_id=api_data["accessScopeId"],
            description=api_data.get("description", ""),
            system_default=is_default,
        )


class Group(BaseModel):
    id: str
    role_name: str
    auth_provider_id: str
    key: str
    value: str

    def __init__(self, api_data: Any) -> None:
        # attributes defined within stackrox(ACS) API for GET /v1/groups
        check_len_attributes(["roleName", "props"], api_data)
        if api_data["roleName"] != "None":
            check_len_attributes(
                ["id", "authProviderId", "key", "value"], api_data["props"]
            )
        else:
            # it is valid for the default None group to contain empty key/value
            check_len_attributes(["id", "authProviderId"], api_data["props"])

        super().__init__(
            role_name=api_data["roleName"],
            id=api_data["props"]["id"],
            auth_provider_id=api_data["props"]["authProviderId"],
            key=api_data["props"]["key"],
            value=api_data["props"]["value"],
        )


class AccessScope(BaseModel):
    id: str
    name: str
    description: str
    clusters: list[str]
    namespaces: list[dict[str, str]]

    def __init__(self, api_data: Any) -> None:
        # attributes defined within stackrox(ACS) API for GET /v1/simpleaccessscopes/{id}
        unrestricted = False
        check_len_attributes(["id", "name"], api_data)

        # it is valid for the default Unrestricted access scope to have null 'rules'
        unrestricted = api_data["name"] == "Unrestricted"
        if not unrestricted:
            check_len_attributes(["rules"], api_data)

        super().__init__(
            id=api_data["id"],
            name=api_data["name"],
            clusters=[]
            if unrestricted
            else api_data["rules"].get("includedClusters", []),
            namespaces=[]
            if unrestricted
            else api_data["rules"].get("includedNamespaces", []),
            description=api_data.get("description", ""),
        )


class PermissionSet(BaseModel):
    id: str
    name: str

    def __init__(self, api_data: Any) -> None:
        # attributes defined within stackrox(ACS) API for GET /v1/permissionsets/{id}
        check_len_attributes(["id", "name"], api_data)

        super().__init__(id=api_data["id"], name=api_data["name"])


class RbacResources(BaseModel):
    roles: list[Role]
    access_scopes: list[AccessScope]
    groups: list[Group]
    permission_sets: list[PermissionSet]


def check_len_attributes(attrs: list[Any], api_data: Any) -> None:
    # generic attribute check function for expected types with valid len()
    for attr in attrs:
        value = api_data.get(attr)
        if value is None or len(value) == 0:
            raise ValueError(
                f"Attribute '{attr}' must exist and not be empty\n\t{api_data}"
            )


class AcsApi:
    def __init__(
        self,
        instance: Any,
        timeout: int = 30,
    ) -> None:
        self.base_url = instance["url"]
        self.token = instance["token"]
        self.timeout = timeout
        self.session = requests.Session()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        self.session.close()

    def generic_request(
        self, path: str, verb: str, json: Optional[Any] = None
    ) -> requests.Response:
        url = f"{self.base_url}{path}"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

        response = self.session.request(
            verb,
            url,
            headers=headers,
            json=json,
            timeout=self.timeout,
        )

        response.raise_for_status()
        return response

    def get_roles(self) -> list[Role]:
        response = self.generic_request("/v1/roles", "GET")
        return [Role(r) for r in response.json()["roles"]]

    def create_role(
        self, name: str, desc: str, permission_set_id: str, access_scope_id: str
    ) -> None:
        json = {
            "name": name,
            "description": desc,
            "permissionSetId": permission_set_id,
            "accessScopeId": access_scope_id,
        }

        self.generic_request(f"/v1/roles/{name}", "POST", json)

    def update_role(
        self, name: str, desc: str, permission_set_id: str, access_scope_id: str
    ) -> None:
        json = {
            "name": name,
            "description": desc,
            "permissionSetId": permission_set_id,
            "accessScopeId": access_scope_id,
        }

        self.generic_request(f"/v1/roles/{name}", "PUT", json)

    def delete_role(self, name: str) -> None:
        self.generic_request(f"/v1/roles/{name}", "DELETE")

    def get_groups(self) -> list[Group]:
        response = self.generic_request("/v1/groups", "GET")
        return [Group(g) for g in response.json()["groups"]]

    class GroupAdd(BaseModel):
        role_name: str
        key: str
        value: str
        auth_provider_id: str

    def create_group_batch(self, additions: list[GroupAdd]) -> None:
        json = {
            "previousGroups": [],
            "requiredGroups": [
                {
                    "roleName": group.role_name,
                    "props": {
                        "id": "",
                        "authProviderId": group.auth_provider_id,
                        "key": group.key,
                        "value": group.value,
                    },
                }
                for group in additions
            ],
        }

        self.generic_request("/v1/groupsbatch", "POST", json)

    def delete_group_batch(self, removals: list[Group]) -> None:
        json = {
            "previousGroups": [
                {
                    "roleName": group.role_name,
                    "props": {
                        "id": group.id,
                        "authProviderId": group.auth_provider_id,
                        "key": group.key,
                        "value": group.value,
                    },
                }
                for group in removals
            ],
            "requiredGroups": [],
        }

        self.generic_request("/v1/groupsbatch", "POST", json)

    def update_group_batch(self, old: list[Group], new: list[GroupAdd]) -> None:
        json = {
            "previousGroups": [
                {
                    "roleName": o.role_name,
                    "props": {
                        "id": o.id,
                        "authProviderId": o.auth_provider_id,
                        "key": o.key,
                        "value": o.value,
                    },
                }
                for o in old
            ],
            "requiredGroups": [
                {
                    "roleName": n.role_name,
                    "props": {
                        "id": "",
                        "authProviderId": n.auth_provider_id,
                        "key": n.key,
                        "value": n.value,
                    },
                }
                for n in new
            ],
        }
        self.generic_request("/v1/groupsbatch", "POST", json)

    def get_access_scopes(self) -> list[AccessScope]:
        response = self.generic_request("/v1/simpleaccessscopes", "GET")
        return [AccessScope(a) for a in response.json()["accessScopes"]]

    def create_access_scope(
        self,
        name: str,
        desc: str,
        clusters: list[str],
        namespaces: list[dict[str, str]],
    ) -> str:
        # response is the created access_scope id
        json = {
            "name": name,
            "description": desc,
            "rules": {
                "includedClusters": clusters,
                "includedNamespaces": namespaces,
            },
        }

        response = self.generic_request("/v1/simpleaccessscopes", "POST", json)

        return response.json()["id"]

    def delete_access_scope(self, id: str) -> None:
        self.generic_request(f"/v1/simpleaccessscopes/{id}", "DELETE")

    def update_access_scope(
        self,
        id: str,
        name: str,
        desc: str,
        clusters: list[str],
        namespaces: list[dict[str, str]],
    ) -> None:
        json = {
            "name": name,
            "description": desc,
            "rules": {
                "includedClusters": clusters,
                "includedNamespaces": namespaces,
            },
        }

        self.generic_request(f"/v1/simpleaccessscopes/{id}", "PUT", json)

    def get_permission_sets(self) -> list[PermissionSet]:
        response = self.generic_request("/v1/permissionsets", "GET")
        return [PermissionSet(p) for p in response.json()["permissionSets"]]

    def get_rbac_resources(self) -> RbacResources:
        return RbacResources(
            roles=self.get_roles(),
            access_scopes=self.get_access_scopes(),
            groups=self.get_groups(),
            permission_sets=self.get_permission_sets(),
        )
