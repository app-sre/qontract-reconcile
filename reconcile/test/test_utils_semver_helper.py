import reconcile.utils.semver_helper as svh


def test_sort_versions():
    versions = ["4.8.0", "4.8.0-rc.0", "4.8.0-fc.1", "4.8.1", "4.8.0-rc.2"]
    expected = ["4.8.0-fc.1", "4.8.0-rc.0", "4.8.0-rc.2", "4.8.0", "4.8.1"]
    assert expected == svh.sort_versions(versions)


def test_is_version_bumped_lower():
    assert svh.is_version_bumped("0.5.0", "0.6.0") is False


def test_is_version_bumped_higher():
    assert svh.is_version_bumped("0.5.0", "0.4.0") is True


def test_is_version_bumped_equal():
    assert svh.is_version_bumped("0.5.0", "0.5.0") is False
