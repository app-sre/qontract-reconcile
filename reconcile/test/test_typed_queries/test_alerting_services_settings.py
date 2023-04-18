from typing import Any

import pytest

from reconcile.test.fixtures import Fixtures
from reconcile.typed_queries.alerting_services_settings import get_alerting_services
from reconcile.utils.exceptions import AppInterfaceSettingsError


@pytest.fixture
def fxt() -> Fixtures:
    return Fixtures("typed_queries")


def test_get_alerting_services(fxt: Fixtures) -> None:
    def q(*args: Any, **kwargs: Any) -> dict[Any, Any]:
        return fxt.get_anymarkup("alerting_services_settings.yml")

    alerting_services = get_alerting_services(q)
    assert alerting_services == {"yak-shaver", "yak-trimmer"}


def test_no_settings() -> None:
    def q(*args: Any, **kwargs: Any) -> dict[Any, Any]:
        return {"settings": []}

    with pytest.raises(AppInterfaceSettingsError):
        get_alerting_services(q)


def test_no_alerting_services(fxt: Fixtures) -> None:
    def q(*args: Any, **kwargs: Any) -> dict[Any, Any]:
        return fxt.get_anymarkup("no-alerting_services_settings.yml")

    with pytest.raises(AppInterfaceSettingsError):
        get_alerting_services(q)
