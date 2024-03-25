import re

import pytest
from pydantic import BaseModel

from reconcile.utils.mergerequest_manager.parser import (
    Parser,
    ParserError,
    ParserVersionError,
)


@pytest.fixture
def data_seperator() -> str:
    return (
        "**TEMPLATE RENDERING DATA - DO NOT MANUALLY CHANGE ANYTHING BELOW THIS LINE**"
    )


@pytest.fixture
def version_ref() -> str:
    return "version_ref"


@pytest.fixture
def data_ref1() -> str:
    return "data_ref1"


@pytest.fixture
def description(data_seperator: str, data_ref1: str, version_ref: str) -> str:
    return f"""
FOO BAR HEADER TEXT

{data_seperator}

* {version_ref}: 1.0.0
* {data_ref1}: data1
"""


@pytest.fixture
def compiled_regexes(version_ref: str, data_ref1: str) -> dict[str, re.Pattern]:
    return {
        i: re.compile(rf".*{i}: (.*)$", re.MULTILINE)
        for i in [
            version_ref,
            data_ref1,
        ]
    }


@pytest.fixture
def parser(
    compiled_regexes: dict[str, re.Pattern],
    version_ref: str,
    data_seperator: str,
) -> Parser:
    return Parser(
        klass=TestModel,
        compiled_regexes=compiled_regexes,
        version_ref=version_ref,
        expected_version="1.0.0",
        data_separator=data_seperator,
    )


class TestModel(BaseModel):
    data_ref1: str


def test_paser_pass(parser: Parser, description: str) -> None:
    result = parser.parse(description)

    assert isinstance(result, TestModel)
    assert result.data_ref1 == "data1"


def test_parser_fail_missing_version(parser: Parser, data_seperator: str) -> None:
    with pytest.raises(
        ParserError,
        match=re.escape(
            "Could not find re.compile('.*version_ref: (.*)$', re.MULTILINE) in MR description"
        ),
    ):
        parser.parse(f"""
TESTING

{data_seperator}
""")


def test_parser_version_fail(parser: Parser, description: str) -> None:
    parser.expected_version = "2.0.0"
    with pytest.raises(ParserVersionError):
        parser.parse(description)


def test_parser_version_fail_seperator(parser: Parser, description: str) -> None:
    parser.data_separator = "AAAAAAAAAAAAAAAAaa"
    with pytest.raises(
        ParserError, match="Could not find data separator in MR description"
    ):
        parser.parse(description)
