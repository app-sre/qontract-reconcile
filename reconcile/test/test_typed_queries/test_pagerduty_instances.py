from typing import Any

import pytest

from reconcile.gql_definitions.common.pagerduty_instances import PagerDutyInstanceV1
from reconcile.gql_definitions.fragments.vault_secret import VaultSecret
from reconcile.test.fixtures import Fixtures
from reconcile.typed_queries.pagerduty_instances import get_pagerduty_instances


@pytest.fixture
def fxt() -> Fixtures:
    return Fixtures("typed_queries")


def test_get_pagerduty_instances(fxt: Fixtures) -> None:
    def q(*args: Any, **kwargs: Any) -> dict[Any, Any]:
        return fxt.get_anymarkup("pagerduty_instances.yml")

    items = get_pagerduty_instances(q)
    assert len(items) == 2
    assert items == [
        PagerDutyInstanceV1(
            name="instance-1",
            token=VaultSecret(
                path="vault-path", field="token", version=None, format=None
            ),
        ),
        PagerDutyInstanceV1(
            name="instance-2",
            token=VaultSecret(
                path="vault-path2", field="token2", version=2, format="format"
            ),
        ),
    ]
