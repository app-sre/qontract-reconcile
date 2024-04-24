import re

import pytest

from reconcile.test.utils.merge_request_manager.conftest import ModelStub
from reconcile.utils.merge_request_manager.parser import (
    Parser,
    ParserError,
    ParserVersionError,
)


def test_paser_pass(parser: Parser, description: str) -> None:
    result = parser.parse(description)

    assert result == ModelStub(data_ref1="data1")


def test_parser_fail_missing_version(parser: Parser) -> None:
    with pytest.raises(
        ParserError,
        match=re.escape(
            "Could not find re.compile('.*version_ref: (.*)$', re.MULTILINE) in MR description"
        ),
    ):
        parser.parse("""
TESTING

**TEMPLATE RENDERING DATA - DO NOT MANUALLY CHANGE ANYTHING BELOW THIS LINE**

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
