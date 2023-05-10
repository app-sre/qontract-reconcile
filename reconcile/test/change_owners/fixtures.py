import copy
import hashlib
import json
from dataclasses import dataclass
from typing import (
    Any,
    Optional,
    Tuple,
)

import jsonpath_ng
import jsonpath_ng.ext

from reconcile.change_owners.bundle import (
    BundleFileType,
    FileDiffResolver,
    FileRef,
)
from reconcile.change_owners.change_types import (
    ChangeTypeProcessor,
    init_change_type_processors,
)
from reconcile.change_owners.changes import (
    BundleFileChange,
    create_bundle_file_change,
)
from reconcile.change_owners.diff import (
    PATH_FIELD_NAME,
    SHA256SUM_FIELD_NAME,
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
    PermissionGitlabGroupMembershipV1,
    PermissionSlackUsergroupV1,
    PermissionV1,
    SelfServiceConfigV1,
    SlackWorkspaceV1,
    UserV1,
)


def _sha256_sum(content: dict[str, Any]) -> str:
    m = hashlib.sha256()
    m.update(json.dumps(content, sort_keys=True).encode("utf-8"))
    return m.hexdigest()


@dataclass
class StubFile:
    filepath: str
    fileschema: Optional[str]
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
        bundle_file_change = create_bundle_file_change(
            path=self.filepath,
            schema=self.fileschema,
            file_type=BundleFileType[self.filetype.upper()],
            old_file_content=StubFile._prepare_content(self.content, self.filepath, {}),
            new_file_content=StubFile._prepare_content(
                self.content, self.filepath, jsonpath_patches
            ),
        )
        assert bundle_file_change
        return bundle_file_change

    @staticmethod
    def _prepare_content(
        content: dict[str, Any], path: str, jsonpath_patches: dict[str, Any]
    ) -> dict[str, Any]:
        new_content = copy.deepcopy(content)
        if jsonpath_patches:
            for jp, v in jsonpath_patches.items():
                e = jsonpath_ng.ext.parse(jp)
                e.update(new_content, v)
        new_content[SHA256SUM_FIELD_NAME] = _sha256_sum(new_content)
        new_content[PATH_FIELD_NAME] = path
        return new_content

    def move(
        self, new_path: str, jsonpath_patches: Optional[dict[str, Any]] = None
    ) -> tuple[BundleFileChange, BundleFileChange]:
        old_bundle_change = create_bundle_file_change(
            path=self.filepath,
            schema=self.fileschema,
            file_type=BundleFileType[self.filetype.upper()],
            old_file_content=StubFile._prepare_content(self.content, self.filepath, {}),
            new_file_content=None,
        )
        new_bundle_change = create_bundle_file_change(
            path=new_path,
            schema=self.fileschema,
            file_type=BundleFileType[self.filetype.upper()],
            old_file_content=None,
            new_file_content=StubFile._prepare_content(
                self.content, new_path, jsonpath_patches or {}
            ),
        )
        assert old_bundle_change
        assert new_bundle_change
        return (old_bundle_change, new_bundle_change)


def build_test_datafile(
    content: dict[str, Any],
    filepath: Optional[str] = None,
    schema: Optional[str] = None,
) -> StubFile:
    return StubFile(
        filepath=filepath or "datafile.yaml",
        fileschema=schema or "schema-1.yml",
        filetype=BundleFileType.DATAFILE.value,
        content=content,
    )


def build_test_resourcefile(
    content: dict[str, Any],
    filepath: Optional[str] = None,
    schema: Optional[str] = None,
) -> StubFile:
    return StubFile(
        filepath=filepath or "path.yaml",
        fileschema=schema,
        filetype=BundleFileType.RESOURCEFILE.value,
        content=content,
    )


def build_role(
    name: str,
    change_type_name: str,
    datafiles: Optional[list[DatafileObjectV1]],
    users: Optional[list[str]] = None,
    bots: Optional[list[str]] = None,
    slack_groups: Optional[list[str]] = None,
    slack_workspace: Optional[str] = "workspace",
    gitlab_groups: Optional[list[str]] = None,
) -> self_service_roles.RoleV1:
    permissions: list[PermissionV1] = [
        PermissionSlackUsergroupV1(
            handle=g, workspace=SlackWorkspaceV1(name=slack_workspace)
        )
        for g in slack_groups or []
    ] + [PermissionGitlabGroupMembershipV1(group=g) for g in gitlab_groups or []]
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
        permissions=permissions,
    )


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
    context_type: BundleFileType = BundleFileType.DATAFILE,
) -> ChangeTypeProcessor:
    return change_type_to_processor(
        ChangeTypeV1(
            name=name,
            description=name,
            contextType=context_type.value,
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
