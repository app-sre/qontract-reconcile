import re
from typing import Generic, TypeVar

from pydantic import BaseModel

from reconcile.utils.models import data_default_none


class ParserError(Exception):
    """Raised when some information cannot be found."""


class ParserVersionError(Exception):
    """Raised when the version is outdated."""


T = TypeVar("T", bound=BaseModel)


class Parser(Generic[T]):
    """This class is only concerned with parsing an MR description rendered by the Renderer."""

    def __init__(
        self,
        klass: type[T],
        compiled_regexes: dict[str, re.Pattern],
        version_ref: str,
        expected_version: str,
        data_separator: str,
    ):
        self.klass = klass
        self.compiled_regexes = compiled_regexes
        self.expected_version = expected_version
        self.version_ref = version_ref
        self.data_separator = data_separator

    @staticmethod
    def _find_by_regex(pattern: re.Pattern, content: str) -> str:
        if matches := pattern.search(content):
            groups = matches.groups()
            if len(groups) == 1:
                return groups[0]

        raise ParserError(f"Could not find {pattern} in MR description")

    def _find_by_name(self, name: str, content: str) -> str:
        return self._find_by_regex(self.compiled_regexes[name], content)

    def _data_from_description(self, description: str) -> dict[str, str]:
        return {
            k: self._find_by_name(k, description)
            for k, v in self.compiled_regexes.items()
        }

    def parse(self, description: str) -> T:
        """Parse the description of an MR"""
        parts = description.split(self.data_separator)
        if not len(parts) == 2:
            raise ParserError("Could not find data separator in MR description")

        if self.expected_version != self._find_by_name(self.version_ref, parts[1]):
            raise ParserVersionError("Version is outdated")
        return self.klass(
            **data_default_none(
                self.klass, self._data_from_description(parts[1]), use_defaults=False
            )
        )
