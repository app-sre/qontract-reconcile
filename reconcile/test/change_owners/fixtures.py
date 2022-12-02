import copy
from dataclasses import dataclass
from typing import (
    Any,
    Optional,
)

import jsonpath_ng
import jsonpath_ng.ext
import pytest

from reconcile.change_owners.change_types import (
    BundleFileChange,
    BundleFileType,
    FileRef,
    create_bundle_file_change,
)
from reconcile.gql_definitions.change_owners.queries import self_service_roles
from reconcile.gql_definitions.change_owners.queries.change_types import ChangeTypeV1
from reconcile.gql_definitions.change_owners.queries.self_service_roles import (
    BotV1,
    DatafileObjectV1,
    RoleV1,
    SelfServiceConfigV1,
    UserV1,
)
from reconcile.test.fixtures import Fixtures

fxt = Fixtures("change_owners")


@dataclass
class TestFile:
    filepath: str
    fileschema: str
    filetype: str
    content: dict[str, Any]

    def file_ref(self) -> FileRef:
        return FileRef(
            path=self.filepath,
            schema=self.fileschema,
            file_type=BundleFileType[self.filetype.upper()],
        )

    def create_bundle_change(
        self, jsonpath_patches: dict[str, Any]
    ) -> BundleFileChange:
        new_content = copy.deepcopy(self.content)
        if jsonpath_patches:
            for jp, v in jsonpath_patches.items():
                e = jsonpath_ng.ext.parse(jp)
                e.update(new_content, v)
        bundle_file_change = create_bundle_file_change(
            path=self.filepath,
            schema=self.fileschema,
            file_type=BundleFileType[self.filetype.upper()],
            old_file_content=self.content,
            new_file_content=new_content,
        )
        assert bundle_file_change
        return bundle_file_change


def build_role(
    name: str,
    change_type_name: str,
    datafiles: Optional[list[DatafileObjectV1]],
    users: Optional[list[str]] = None,
    bots: Optional[list[str]] = None,
) -> self_service_roles.RoleV1:
    return self_service_roles.RoleV1(
        name=name,
        path=f"/role/{name}.yaml",
        self_service=[
            SelfServiceConfigV1(
                change_type=self_service_roles.ChangeTypeV1(
                    name=change_type_name, contextSchema=None
                ),
                datafiles=datafiles,
                resources=None,
            )
        ],
        users=[
            UserV1(org_username=u, tag_on_merge_requests=False) for u in users or []
        ],
        bots=[BotV1(org_username=b) for b in bots or []],
    )


def load_change_type(path: str) -> ChangeTypeV1:
    content = fxt.get_anymarkup(path)
    return ChangeTypeV1(**content)


def load_self_service_roles(path: str) -> list[RoleV1]:
    roles = fxt.get_anymarkup(path)["self_service_roles"]
    return [RoleV1(**r) for r in roles]


@pytest.fixture
def saas_file_changetype() -> ChangeTypeV1:
    return load_change_type("changetype_saas_file.yaml")


@pytest.fixture
def role_member_change_type() -> ChangeTypeV1:
    return load_change_type("changetype_role_member.yaml")


@pytest.fixture
def cluster_owner_change_type() -> ChangeTypeV1:
    return load_change_type("changetype_cluster_owner.yml")


@pytest.fixture
def secret_promoter_change_type() -> ChangeTypeV1:
    return load_change_type("changetype_secret_promoter.yaml")


@pytest.fixture
def change_types() -> list[ChangeTypeV1]:
    return [saas_file_changetype(), role_member_change_type()]


@pytest.fixture
def saas_file() -> TestFile:
    return TestFile(**fxt.get_anymarkup("datafile_saas_file.yaml"))


@pytest.fixture
def user_file() -> TestFile:
    return TestFile(**fxt.get_anymarkup("datafile_user.yaml"))


@pytest.fixture
def namespace_file() -> TestFile:
    return TestFile(**fxt.get_anymarkup("datafile_namespace.yaml"))


@pytest.fixture
def rds_defaults_file() -> TestFile:
    return TestFile(**fxt.get_anymarkup("resourcefile_rds_defaults.yaml"))
