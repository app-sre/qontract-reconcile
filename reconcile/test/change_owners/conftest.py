import pytest

from reconcile.gql_definitions.change_owners.queries.change_types import ChangeTypeV1
from reconcile.test.change_owners.fixtures import StubFile
from reconcile.test.fixtures import Fixtures

fxt = Fixtures("change_owners")


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
def saas_file() -> StubFile:
    return StubFile(**fxt.get_anymarkup("datafile_saas_file.yaml"))


@pytest.fixture
def user_file() -> StubFile:
    return StubFile(**fxt.get_anymarkup("datafile_user.yaml"))


@pytest.fixture
def namespace_file() -> StubFile:
    return StubFile(**fxt.get_anymarkup("datafile_namespace.yaml"))


@pytest.fixture
def rds_defaults_file() -> StubFile:
    return StubFile(**fxt.get_anymarkup("resourcefile_rds_defaults.yaml"))


def load_change_type(path: str) -> ChangeTypeV1:
    content = fxt.get_anymarkup(path)
    return ChangeTypeV1(**content)
