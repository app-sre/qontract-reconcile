from collections.abc import Callable

import pytest
from pytest_mock import MockerFixture

from reconcile.rhidp.common import Cluster
from reconcile.test.fixtures import Fixtures
from reconcile.utils.ocm_base_client import OCMBaseClient


@pytest.fixture
def fx() -> Fixtures:
    return Fixtures("rhidp")


@pytest.fixture
def clusters(gql_class_factory: Callable, fx: Fixtures) -> list[Cluster]:
    return [gql_class_factory(Cluster, c) for c in fx.get_anymarkup("clusters.yml")]


@pytest.fixture
def ocm_base_client(mocker: MockerFixture) -> OCMBaseClient:
    return mocker.create_autospec(spec=OCMBaseClient)
