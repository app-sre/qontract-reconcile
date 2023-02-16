from datetime import (
    datetime,
    timedelta,
    timezone,
)

from reconcile.gql_definitions.statuspage.statuspages import (
    ManualStatusProviderConfigV1,
    ManualStatusProviderV1,
    StatusProviderV1,
)
from reconcile.statuspage.status import (
    ManualStatusProvider,
    build_status_provider_config,
)


def test_manual_status_provider():
    provider = ManualStatusProvider(component_status="operational")
    assert provider.get_status() == "operational"


def test_manual_status_provider_active_period():
    now = datetime.now(timezone.utc)
    bounded_period = ManualStatusProvider(
        start=now,
        end=now + timedelta(days=1),
        component_status="operational",
    )
    assert bounded_period.get_status() == "operational"

    open_start_period = ManualStatusProvider(
        start=None,
        end=now + timedelta(days=1),
        component_status="operational",
    )
    assert open_start_period.get_status() == "operational"

    open_end_period = ManualStatusProvider(
        start=now,
        end=None,
        component_status="operational",
    )
    assert open_end_period.get_status() == "operational"


def test_manual_status_provider_inactive_period():
    now = datetime.now(timezone.utc)
    past_period = ManualStatusProvider(
        start=None,
        end=now - timedelta(minutes=1),
        component_status="operational",
    )
    assert past_period.get_status() is None

    open_past_period = ManualStatusProvider(
        start=now - timedelta(minutes=2),
        end=now - timedelta(minutes=1),
        component_status="operational",
    )
    assert open_past_period.get_status() is None

    open_future_period = ManualStatusProvider(
        start=now + timedelta(days=1),
        end=None,
        component_status="operational",
    )
    assert open_future_period.get_status() is None

    future_period = ManualStatusProvider(
        start=now + timedelta(days=1),
        end=now + timedelta(days=2),
        component_status="operational",
    )
    assert future_period.get_status() is None


def test_build_manual_status_provider_from_desired_state() -> None:
    config = ManualStatusProviderV1(
        provider="manual",
        manual=ManualStatusProviderConfigV1(
            **{
                "componentStatus": "operational",
                "from": "2021-01-01T00:00:00Z",
                "until": "2021-01-02T00:00:00Z",
            }
        ),
    )
    manual_provider = build_status_provider_config(config)
    assert isinstance(manual_provider, ManualStatusProvider)
    assert manual_provider.component_status == "operational"
    assert manual_provider.start
    assert manual_provider.end


def test_build_unknown_from_desired_state() -> None:
    class UnknownStatusProviderV1(StatusProviderV1):
        pass

    config = UnknownStatusProviderV1(provider="unknown-provider")
    manual_provider = build_status_provider_config(config)
    assert manual_provider is None
