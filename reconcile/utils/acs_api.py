import requests

from pydantic import BaseModel
from typing import Any


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
        try:
            check_len_attributes(
                ["id", "authProviderId", "key", "value"], api_data["props"]
            )
        except ValueError as e:
            # it is valid for the default None group to contain empty key/value
            if api_data["roleName"] != "None":
                raise e

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
        try:
            check_len_attributes(["id", "name", "rules"], api_data)
        except ValueError as e:
            # it is valid for the default Unrestricted access scope to have null `rules`
            if api_data.get("name") != "Unrestricted":
                raise e
            unrestricted = True

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
        self.url = instance["url"]
        self.token = instance["token"]
        self.timeout = timeout

    def generic_get_request(self, path: str) -> requests.Response:
        response = requests.get(
            url=f"{self.url}{path}",
            headers={"Authorization": f"Bearer {self.token}"},
            timeout=self.timeout,
        )
        try:
            response.raise_for_status()
        except requests.exceptions.RequestException as details:
            raise requests.exceptions.RequestException(
                f"Failed to perform GET request:\n\t{details}\n\t{response.text}"
            )

        return response

    def generic_post_request(self, path: str, json: Any) -> requests.Response:
        response = requests.post(
            url=f"{self.url}{path}",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            },
            timeout=self.timeout,
            json=json,
        )

        try:
            response.raise_for_status()
        except requests.exceptions.RequestException as details:
            raise requests.exceptions.RequestException(
                f"Failed to perform POST request with body:\n\t{json}\n\t{details}\n\t{response.text}"
            )

        return response

    def generic_put_request(self, path: str, json: Any) -> requests.Response:
        response = requests.put(
            url=f"{self.url}{path}",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            },
            timeout=self.timeout,
            json=json,
        )

        try:
            response.raise_for_status()
        except requests.exceptions.RequestException as details:
            raise requests.exceptions.RequestException(
                f"Failed to perform PUT request with body:\n\t{json}\n\t{details}\n\t{response.text}"
            )

        return response

    def generic_delete_request(self, path: str) -> requests.Response:
        response = requests.delete(
            url=f"{self.url}{path}",
            headers={
                "Authorization": f"Bearer {self.token}",
            },
            timeout=self.timeout,
        )

        try:
            response.raise_for_status()
        except requests.exceptions.RequestException as details:
            raise requests.exceptions.RequestException(
                f"Failed to perform DELETE request:\n\t{details}\n\t{response.text}"
            )

        return response

    def get_roles(self) -> list[Role]:
        response = self.generic_get_request("/v1/roles")

        roles = []
        for role in response.json()["roles"]:
            roles.append(Role(role))
        return roles

    def create_role(
        self, name: str, desc: str, permission_set_id: str, access_scope_id: str
    ) -> None:
        json = {
            "name": name,
            "description": desc,
            "permissionSetId": permission_set_id,
            "accessScopeId": access_scope_id,
        }

        self.generic_post_request(f"/v1/roles/{name}", json)

    def update_role(
        self, name: str, desc: str, permission_set_id: str, access_scope_id: str
    ) -> None:
        json = {
            "name": name,
            "description": desc,
            "permissionSetId": permission_set_id,
            "accessScopeId": access_scope_id,
        }

        self.generic_put_request(f"/v1/roles/{name}", json)

    def delete_role(self, name: str) -> None:
        self.generic_delete_request(f"/v1/roles/{name}")

    def get_groups(self) -> list[Group]:
        response = self.generic_get_request("/v1/groups")

        groups = []
        for group in response.json()["groups"]:
            groups.append(Group(group))

        return groups

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

        self.generic_post_request("/v1/groupsbatch", json)

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

        self.generic_post_request("/v1/groupsbatch", json)

    def patch_group_batch(self, old: list[Group], new: list[GroupAdd]) -> None:
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
        self.generic_post_request("/v1/groupsbatch", json)

    def get_access_scope_by_id(self, id: str) -> AccessScope:
        response = self.generic_get_request(f"/v1/simpleaccessscopes/{id}")

        return AccessScope(response.json())

    def get_access_scopes(self) -> list[AccessScope]:
        response = self.generic_get_request("/v1/simpleaccessscopes")

        access_scopes = []
        for scope in response.json()["accessScopes"]:
            access_scopes.append(AccessScope(scope))

        return access_scopes

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

        response = self.generic_post_request("/v1/simpleaccessscopes", json)

        return response.json()["id"]

    def delete_access_scope(self, id: str) -> None:
        self.generic_delete_request(f"/v1/simpleaccessscopes/{id}")

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

        self.generic_put_request(f"/v1/simpleaccessscopes/{id}", json)

    def get_permission_set_by_id(self, id: str) -> PermissionSet:
        response = self.generic_get_request(f"/v1/permissionsets/{id}")

        return PermissionSet(response.json())

    def get_permission_sets(self) -> list[PermissionSet]:
        response = self.generic_get_request("/v1/permissionsets")

        permission_sets = []
        for ps in response.json()["permissionSets"]:
            permission_sets.append(PermissionSet(ps))

        return permission_sets
