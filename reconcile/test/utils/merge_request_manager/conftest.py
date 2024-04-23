import re

import pytest
from pydantic import BaseModel

from reconcile.utils.merge_request_manager.parser import Parser

desc_string = """
FOO BAR HEADER TEXT

**TEMPLATE RENDERING DATA - DO NOT MANUALLY CHANGE ANYTHING BELOW THIS LINE**

* {version_ref}: 1.0.0
* {data_ref1}: data1
"""


@pytest.fixture
def version_ref() -> str:
    return "version_ref"


@pytest.fixture
def data_ref1() -> str:
    return "data_ref1"


@pytest.fixture
def description(data_ref1: str, version_ref: str) -> str:
    return desc_string.format(version_ref=version_ref, data_ref1=data_ref1)


@pytest.fixture
def compiled_regexes(version_ref: str, data_ref1: str) -> dict[str, re.Pattern]:
    return {
        i: re.compile(rf".*{i}: (.*)$", re.MULTILINE)
        for i in [
            version_ref,
            data_ref1,
        ]
    }


class TstModel(BaseModel):
    data_ref1: str


@pytest.fixture
def parser(
    compiled_regexes: dict[str, re.Pattern],
    version_ref: str,
) -> Parser:
    return Parser[TstModel](
        klass=TstModel,
        compiled_regexes=compiled_regexes,
        version_ref=version_ref,
        expected_version="1.0.0",
        data_separator="**TEMPLATE RENDERING DATA - DO NOT MANUALLY CHANGE ANYTHING BELOW THIS LINE**",
    )
