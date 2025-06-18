from collections.abc import Iterable

import pytest

from reconcile.utils.output import format_table


@pytest.fixture
def content() -> Iterable[dict]:
    return [
        {"a": "a1", "b": {"b": "b1"}, "c": ["1", "2"]},
        {"a": "a2", "b": {"b": "b2"}, "c": ["1", "2"]},
        {"a": "a3", "b": {"b": "b3"}, "c": ["1", "2"]},
    ]


def test_format_table_simple(content: Iterable[dict]) -> None:
    output = format_table(
        content,
        ["a", "b", "b.b", "c"],
        "simple",
    )

    assert (
        output
        == "A    B            B.B    C\n---  -----------  -----  ---\na1   {'b': 'b1'}  b1     1\n                         2\na2   {'b': 'b2'}  b2     1\n                         2\na3   {'b': 'b3'}  b3     1\n                         2"
    )


def test_format_table_github(content: Iterable[dict]) -> None:
    output = format_table(
        content,
        ["a", "b", "b.b", "c"],
        "github",
    )

    assert (
        output
        == "| A   | B           | B.B   | C        |\n|-----|-------------|-------|----------|\n| a1  | {'b': 'b1'} | b1    | 1<br />2 |\n| a2  | {'b': 'b2'} | b2    | 1<br />2 |\n| a3  | {'b': 'b3'} | b3    | 1<br />2 |"
    )


def test_format_table_missing_column_field(content: Iterable[dict]) -> None:
    output = format_table(
        content,
        ["non_existant"],
    )

    assert output == "NON_EXISTANT\n--------------\n\n\n"
