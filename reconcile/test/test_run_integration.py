from __future__ import annotations

import click

from reconcile.run_integration import build_entry_point_args


@click.group()
def _cli() -> None:
    pass


@_cli.command(name="some-integration")
def some_integration() -> None:
    pass


def test_build_entry_point_args_splits_plain_extra_args() -> None:
    args = build_entry_point_args(
        _cli, "config.toml", "--dry-run", "some-integration", "--foo bar --baz"
    )

    assert args == [
        "--config",
        "config.toml",
        "--dry-run",
        "some-integration",
        "--foo",
        "bar",
        "--baz",
    ]


def test_build_entry_point_args_keeps_quoted_arg_with_spaces_as_one_token() -> None:
    extra_args = (
        '--keycloak-instances \'{"url": "https://example.com", "secret": {"a": "b"}}\''
    )

    args = build_entry_point_args(
        _cli, "config.toml", "--dry-run", "some-integration", extra_args
    )

    assert args == [
        "--config",
        "config.toml",
        "--dry-run",
        "some-integration",
        "--keycloak-instances",
        '{"url": "https://example.com", "secret": {"a": "b"}}',
    ]
