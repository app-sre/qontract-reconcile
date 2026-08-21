import pytest

from reconcile.utils.ocm.products import (
    OCMProductHypershift,
    OCMProductOsd,
    OCMProductRosa,
    build_ystream_channel,
)


@pytest.mark.parametrize(
    ("channel_group", "version", "expected"),
    [
        ("stable", "4.8.10", "stable-4.8"),
        ("stable", "4.16.0", "stable-4.16"),
        ("eus", "4.16.3", "eus-4.16"),
        ("candidate", "4.10", "candidate-4.10"),
    ],
)
def test_build_ystream_channel(channel_group: str, version: str, expected: str) -> None:
    assert build_ystream_channel(channel_group, version) == expected


def test_osd_update_spec_channel_is_ystream() -> None:
    spec = OCMProductOsd()._get_update_cluster_spec({"channel": "stable"}, "4.16.0")
    assert spec == {"channel": "stable-4.16"}


def test_rosa_update_spec_channel_is_ystream() -> None:
    spec = OCMProductRosa(None)._get_update_cluster_spec(
        {"channel": "stable"}, "4.16.0"
    )
    assert spec == {"channel": "stable-4.16"}


def test_hypershift_update_spec_channel_is_ystream() -> None:
    # Regression: SPEC_ATTR_CHANNEL is in Hypershift's ALLOWED_SPEC_UPDATE_FIELDS,
    # so a channel change must be translated into the OCM PATCH body instead of
    # being silently dropped (which caused an endless no-op reconcile loop).
    spec = OCMProductHypershift(None)._get_update_cluster_spec(
        {"channel": "stable"}, "4.16.0"
    )
    assert spec == {"channel": "stable-4.16"}
