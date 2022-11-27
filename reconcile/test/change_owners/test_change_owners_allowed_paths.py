import pytest

from reconcile.change_owners.change_types import (
    ChangeTypeContext,
    FileRef,
    BundleFileType,
    build_change_type_processor,
)
from reconcile.test.fixtures import Fixtures

from reconcile.test.change_owners.utils import (
    TestFile,
    MockQuerier,
    build_change_role_member_changetype,
    build_secret_promoter_changetype,
    build_saas_file_target_cluster_owner_changetype,
)

fxt = Fixtures("change_owners")

#
# change type processor find allowed changed paths
#


@pytest.fixture
def namespace_file() -> TestFile:
    return TestFile(**fxt.get_anymarkup("datafile_namespace.yaml"))


@pytest.fixture
def user_file() -> TestFile:
    return TestFile(**fxt.get_anymarkup("datafile_user.yaml"))


@pytest.fixture
def saas_file() -> TestFile:
    return TestFile(**fxt.get_anymarkup("datafile_saas_file.yaml"))


def test_change_type_processor_allowed_paths_simple(user_file: TestFile):
    role_member_changetype = build_change_role_member_changetype()
    changed_user_file = user_file.create_bundle_change(
        {"roles[0]": {"$ref": "some-role"}}
    )
    processor = build_change_type_processor(role_member_changetype)
    paths = processor.allowed_changed_paths(
        file_ref=changed_user_file.fileref,
        file_content=changed_user_file.new,
        ctx=ChangeTypeContext(
            change_type_processor=processor,
            context="RoleV1 - some role",
            approvers=[],
            context_file=user_file.file_ref(),
        ),
        querier=MockQuerier(),
    )

    assert paths == ["roles"]


def test_change_type_processor_allowed_paths_conditions(namespace_file: TestFile):
    secret_promoter_changetype = build_secret_promoter_changetype()
    changed_namespace_file = namespace_file.create_bundle_change(
        {"openshiftResources[1].version": 2}
    )
    processor = build_change_type_processor(secret_promoter_changetype)
    paths = processor.allowed_changed_paths(
        file_ref=changed_namespace_file.fileref,
        file_content=changed_namespace_file.new,
        ctx=ChangeTypeContext(
            change_type_processor=processor,
            context="RoleV1 - some role",
            approvers=[],
            context_file=namespace_file.file_ref(),
        ),
        querier=MockQuerier(),
    )

    assert paths == ["openshiftResources.[1].version"]


def test_change_type_processor_allowed_paths_templated():
    my_namespace = "my-namespace.yml"
    owned_cluster = "my-cluster.yml"
    saas_file = TestFile(
        filepath="path",
        fileschema="/app-sre/saas-file-2.yml",
        filetype="datafile",
        content={
            "resourceTemplates": [
                {"targets": [{"namespace": {"$ref": "another-one.yml"}}]},
                {
                    "targets": [
                        {"namespace": {"$ref": my_namespace}},
                        {"namespace": {"$ref": "one-more.yml"}},
                    ]
                },
            ]
        },
    )
    change_type = build_saas_file_target_cluster_owner_changetype()
    processor = build_change_type_processor(change_type)

    paths = processor.allowed_changed_paths(
        file_ref=saas_file.file_ref(),
        file_content=saas_file.content,
        ctx=ChangeTypeContext(
            change_type_processor=processor,
            context="RoleV1 - some role",
            approvers=[],
            context_file=FileRef(
                path=owned_cluster,
                file_type=BundleFileType.DATAFILE,
                schema="/openshift/cluster-1.yml",
            ),
        ),
        querier=MockQuerier(
            [
                {
                    "clusters_v1": [
                        {
                            "path": owned_cluster,
                            "namespaces": [{"path": my_namespace}],
                        },
                        {
                            "path": "another-cluster.yml",
                            "namespaces": [{"path": "another-one.yml"}],
                        },
                    ]
                }
            ]
        ),
    )
    assert paths == ["resourceTemplates.[1].targets.[0]"]
