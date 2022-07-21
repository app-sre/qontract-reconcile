import os
import threading
from queue import Queue

from UnleashClient import UnleashClient
from UnleashClient.features import Feature
from UnleashClient.strategies import Strategy

from reconcile.utils.unleash import (
    _get_unleash_api_client,
    get_feature_toggle_default,
    get_feature_toggle_state,
    get_feature_toggles,
    get_feature_toggle_strategies,
)


class Local:
    client: None


def test__get_unleash_api_client(mocker):
    a = mocker.patch("UnleashClient.UnleashClient.initialize_client")
    c = _get_unleash_api_client("https://u/api", "foo", local=Local)

    assert a.call_count == 1
    assert Local.client == c


def test__get_unleash_api_client_skip_create(mocker):
    u = mocker.patch("UnleashClient.UnleashClient")
    Local.client = u
    a = mocker.patch("UnleashClient.UnleashClient.initialize_client")
    c = _get_unleash_api_client("https://u/api", "foo", local=Local)

    assert a.call_count == 0
    assert Local.client == c == u


def test_get_feature_toggle_default():
    assert get_feature_toggle_default(None, None)


def test_get_feature_toggle_state_env_missing():
    assert get_feature_toggle_state("foo")


def test_get_feature_toggle_state(mocker):
    def enabled_func(feature, fallback_function):
        return feature == "enabled"

    os.environ["UNLEASH_API_URL"] = "foo"
    os.environ["UNLEASH_CLIENT_ACCESS_TOKEN"] = "bar"

    defaultfunc = mocker.patch(
        "reconcile.utils.unleash.get_feature_toggle_default", return_value=True
    )
    mocker.patch("UnleashClient.UnleashClient.initialize_client")
    mocker.patch("UnleashClient.UnleashClient.is_enabled", side_effect=enabled_func)

    assert get_feature_toggle_state("enabled")
    assert get_feature_toggle_state("disabled") is False
    assert defaultfunc.call_count == 0


def test_get_feature_toggles(mocker):
    c = mocker.patch("UnleashClient.UnleashClient")
    c.features = {
        "foo": Feature("foo", False, []),
        "bar": Feature("bar", True, []),
    }

    mocker.patch("reconcile.utils.unleash._get_unleash_api_client", return_value=c)
    toggles = get_feature_toggles("api", "token")

    assert toggles["foo"] == "disabled"
    assert toggles["bar"] == "enabled"


def test_get_feature_toggle_strategies_env_missing():
    assert get_feature_toggle_strategies("foo") is None


def test_get_feature_toggle_strategies(mocker):
    os.environ["UNLEASH_API_URL"] = "foo"
    os.environ["UNLEASH_CLIENT_ACCESS_TOKEN"] = "bar"

    c = mocker.patch("UnleashClient.UnleashClient")
    c.features = {
        "foo": Feature("foo", False, [Strategy(parameters={"foo": "bar"})]),
        "bar": Feature("bar", True, []),
    }

    mocker.patch("reconcile.utils.unleash._get_unleash_api_client", return_value=c)

    strategies = get_feature_toggle_strategies("foo")
    assert strategies is not None and len(strategies) == 1
    assert strategies[0].parameters["foo"] == "bar"

    strategies = get_feature_toggle_strategies("bar")
    assert strategies is not None and len(strategies) == 0

    assert get_feature_toggle_strategies("rab") is None


def test__get_unleash_api_client_threaded(mocker):
    q: Queue[UnleashClient] = Queue()
    mocker.patch("UnleashClient.UnleashClient.initialize_client")

    def threaded():
        q.put(_get_unleash_api_client("https://u/api", "foo"))

    for _ in range(0, 2):
        t = threading.Thread(target=threaded)
        t.start()
        t.join()

    assert q.qsize() == 2
    a = q.get()
    b = q.get()
    assert a != b
    assert isinstance(a, UnleashClient)
    assert isinstance(b, UnleashClient)
