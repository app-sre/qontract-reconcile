import copy
from dataclasses import dataclass
from typing import (
    Any,
    Optional,
    Tuple,
)

import jsonpath_ng
import jsonpath_ng.ext
import pytest

from reconcile.change_owners.bundle import (
    BundleFileType,
    FileDiffResolver,
    FileRef,
)
from reconcile.change_owners.change_types import (
    BundleFileChange,
    ChangeTypeProcessor,
    create_bundle_file_change,
    init_change_type_processors,
)
from reconcile.gql_definitions.change_owners.queries import self_service_roles
from reconcile.gql_definitions.change_owners.queries.change_types import (
    ChangeTypeChangeDetectorChangeTypeProviderV1,
    ChangeTypeChangeDetectorChangeTypeProviderV1_ChangeTypeChangeDetectorContextSelectorV1,
    ChangeTypeChangeDetectorChangeTypeProviderV1_ChangeTypeV1,
    ChangeTypeChangeDetectorContextSelectorV1,
    ChangeTypeChangeDetectorJsonPathProviderV1,
    ChangeTypeV1,
)
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


def build_test_datafile(
    content: dict[str, Any],
    filepath: Optional[str] = None,
    schema: Optional[str] = None,
) -> TestFile:
    return TestFile(
        filepath=filepath or "datafile.yaml",
        fileschema=schema or "schema-1.yml",
        filetype=BundleFileType.DATAFILE.value,
        content=content,
    )


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


def build_jsonpath_change(
    selectors: list[str],
    schema: Optional[str] = None,
    context_selector: Optional[str] = None,
    context_when: Optional[str] = None,
) -> ChangeTypeChangeDetectorJsonPathProviderV1:
    if context_selector:
        context = ChangeTypeChangeDetectorContextSelectorV1(
            selector=context_selector, when=context_when
        )
    else:
        context = None
    return ChangeTypeChangeDetectorJsonPathProviderV1(
        provider="jsonPath",
        changeSchema=schema,
        jsonPathSelectors=selectors,
        context=context,
    )


def build_change_type_change(
    schema: str,
    change_type_names: list[str],
    context_selector: str,
    context_when: Optional[str],
) -> ChangeTypeChangeDetectorChangeTypeProviderV1:
    return ChangeTypeChangeDetectorChangeTypeProviderV1(
        provider="changeType",
        changeSchema=schema,
        changeTypes=[
            ChangeTypeChangeDetectorChangeTypeProviderV1_ChangeTypeV1(
                contextSchema=None,
                name=name,
            )
            for name in change_type_names
        ],
        ownership_context=ChangeTypeChangeDetectorChangeTypeProviderV1_ChangeTypeChangeDetectorContextSelectorV1(
            selector=context_selector,
            when=context_when,
        ),
    )


def build_change_type(
    name: str,
    change_selectors: list[str],
    change_schema: Optional[str] = None,
    context_schema: Optional[str] = None,
) -> ChangeTypeProcessor:
    return change_type_to_processor(
        ChangeTypeV1(
            name=name,
            description=name,
            contextType=BundleFileType.DATAFILE.value,
            contextSchema=context_schema,
            changes=[
                build_jsonpath_change(
                    schema=change_schema,
                    selectors=change_selectors,
                )
            ],
            disabled=False,
            priority="urgent",
            inherit=[],
            implicitOwnership=[],
        ),
    )


class MockFileDiffResolver:
    def __init__(
        self,
        fail_on_unknown_path: Optional[bool] = True,
        file_diffs: Optional[
            dict[str, Tuple[Optional[dict[str, Any]], Optional[dict[str, Any]]]]
        ] = None,
    ):
        self.file_diffs = file_diffs or {}
        self.fail_on_unknown_path = fail_on_unknown_path

    def register_raw_diff(
        self, path: str, old: Optional[dict[str, Any]], new: Optional[dict[str, Any]]
    ) -> "MockFileDiffResolver":
        self.file_diffs[path] = (old, new)
        return self

    def register_bundle_change(
        self,
        bundle_change: BundleFileChange,
    ) -> "MockFileDiffResolver":
        return self.register_raw_diff(
            bundle_change.fileref.path, bundle_change.old, bundle_change.new
        )

    def lookup_file_diff(
        self, file_ref: FileRef
    ) -> Tuple[Optional[dict[str, Any]], Optional[dict[str, Any]]]:
        if file_ref.path not in self.file_diffs and self.fail_on_unknown_path:
            raise Exception(f"no diff registered for {file_ref.path}")
        return self.file_diffs.get(file_ref.path, (None, None))


def change_type_to_processor(
    change_type: ChangeTypeV1, file_diff_resolver: Optional[FileDiffResolver] = None
) -> ChangeTypeProcessor:
    return init_change_type_processors(
        [change_type],
        file_diff_resolver or MockFileDiffResolver(fail_on_unknown_path=False),
    )[change_type.name]
