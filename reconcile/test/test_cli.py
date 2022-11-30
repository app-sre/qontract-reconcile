import pytest
from click.testing import CliRunner

import reconcile.cli as reconcile_cli


def test_config_is_required():
    runner = CliRunner()
    result = runner.invoke(reconcile_cli.integration)
    assert result.exit_code == 0


def test_parse_image_tag_from_ref_valid():
    t = ("env=main",)
    expected = {"env": "main"}
    result = reconcile_cli.parse_image_tag_from_ref(None, None, t)
    assert result == expected


def test_parse_image_tag_from_ref_invalid_1():
    t = ("env=",)
    with pytest.raises(SystemExit):
        reconcile_cli.parse_image_tag_from_ref(None, None, t)


def test_parse_image_tag_from_ref_invalid_2():
    t = ("=main",)
    with pytest.raises(SystemExit):
        reconcile_cli.parse_image_tag_from_ref(None, None, t)


def test_parse_image_tag_from_ref_invalid_3():
    t = ("=",)
    with pytest.raises(SystemExit):
        reconcile_cli.parse_image_tag_from_ref(None, None, t)


def test_parse_image_tag_from_ref_invalid_4():
    t = ("env=main=test",)
    with pytest.raises(SystemExit):
        reconcile_cli.parse_image_tag_from_ref(None, None, t)
