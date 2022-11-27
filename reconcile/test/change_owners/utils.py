from typing import Any, Optional
from dataclasses import dataclass
import copy

from reconcile.change_owners.change_types import (
    BundleFileChange,
    BundleFileType,
    FileRef,
    create_bundle_file_change,
)

from reconcile.gql_definitions.change_owners.queries.change_types import (
    ChangeTypeChangeDetectorJsonPathProviderV1,
    ChangeTypeV1,
    ChangeTypeChangeDetectorContextSelectorV1,
    ChangeTypeChangeDetectorJsonPathSelectorTemplateV1,
)

import jsonpath_ng
import jsonpath_ng.ext


class MockQuerier:
    def __init__(self, results: Optional[list[dict[str, Any]]] = None):
        self.results = results

    def query(
        self,
        query: str,
        variables: Optional[dict[str, Any]] = None,
        skip_validation: Optional[bool] = False,
    ) -> Optional[dict[str, Any]]:
        if self.results:
            return self.results.pop(0)
        else:
            raise Exception("MockQuerier: no more results")


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


def build_change_role_member_changetype() -> ChangeTypeV1:
    return ChangeTypeV1(
        name="change-role-member",
        description="change-role-member",
        contextSchema="/access/role-1.yml",
        contextType="datafile",
        disabled=False,
        priority="high",
        inherit=None,
        changes=[
            ChangeTypeChangeDetectorJsonPathProviderV1(
                provider="jsonPath",
                jsonPathSelectors=[
                    "roles",
                ],
                jsonPathSelectorTemplates=None,
                changeSchema="/access/user-1.yml",
                context=ChangeTypeChangeDetectorContextSelectorV1(
                    selector="roles[*].'$ref'", when="added"
                ),
            )
        ],
    )


def build_saas_file_changetype() -> ChangeTypeV1:
    return ChangeTypeV1(
        name="saas-file",
        description="saas file change",
        contextSchema="/app-sre/saas-file-2.yml",
        contextType="datafile",
        disabled=False,
        priority="high",
        inherit=None,
        changes=[
            ChangeTypeChangeDetectorJsonPathProviderV1(
                provider="jsonPath",
                jsonPathSelectors=[
                    "deployResources",
                    "parameters",
                    "resourceTemplates[*].parameters",
                    "resourceTemplates[*].targets[*].ref",
                    "resourceTemplates[*].targets[*].parameters",
                    "resourceTemplates[*].targets[*].secretParameters[*].version",
                    "resourceTemplates[*].targets[*].upstream",
                    "resourceTemplates[*].targets[*].disable",
                ],
                jsonPathSelectorTemplates=None,
                changeSchema=None,
                context=None,
            )
        ],
    )


def build_saas_file_target_cluster_owner_changetype() -> ChangeTypeV1:
    return ChangeTypeV1(
        name="saas-file-target-cluster-owner",
        description="saas-file-target-cluster-owner",
        contextSchema="/openshift/cluster-1.yml",
        contextType="datafile",
        disabled=False,
        priority="high",
        inherit=None,
        changes=[
            ChangeTypeChangeDetectorJsonPathProviderV1(
                provider="jsonPath",
                jsonPathSelectors=None,
                jsonPathSelectorTemplates=[
                    ChangeTypeChangeDetectorJsonPathSelectorTemplateV1(
                        items="gql+jsonpath://clusters_v1[?(@.path=='{{ ctx_file_path }}')].namespaces[*].path",
                        var="ns",
                        template="resourceTemplates[*].targets[?(@.namespace.'$ref'=='{{ ns }}')]",
                    )
                ],
                changeSchema="/app-sre/saas-file-2.yml",
                context=ChangeTypeChangeDetectorContextSelectorV1(
                    selector="gql+jsonpath://saas_files_v2[?(@.path=='{{ changed_file_path }}')].resourceTemplates[*].targets[*].namespace.cluster.path",
                    when="added",
                ),
            )
        ],
    )


def build_cluster_owner_changetype() -> ChangeTypeV1:
    return ChangeTypeV1(
        name="cluster-owner",
        description="cluster-owner",
        contextSchema="/openshift/cluster-1.yml",
        contextType="datafile",
        disabled=False,
        priority="high",
        inherit=None,
        changes=[
            ChangeTypeChangeDetectorJsonPathProviderV1(
                provider="jsonPath",
                jsonPathSelectors=[
                    "$",
                ],
                jsonPathSelectorTemplates=None,
                changeSchema="/openshift/namespace-1.yml",
                context=ChangeTypeChangeDetectorContextSelectorV1(
                    selector="cluster.'$ref'", when=None
                ),
            )
        ],
    )


def build_secret_promoter_changetype() -> ChangeTypeV1:
    return ChangeTypeV1(
        name="secret-promoter",
        description="secret-promoter",
        contextSchema="/openshift/namespace-1.yml",
        contextType="datafile",
        disabled=False,
        priority="high",
        inherit=None,
        changes=[
            ChangeTypeChangeDetectorJsonPathProviderV1(
                provider="jsonPath",
                jsonPathSelectors=[
                    "openshiftResources[?(@.provider=='vault-secret')].version",
                ],
                jsonPathSelectorTemplates=None,
                changeSchema=None,
                context=None,
            )
        ],
    )
