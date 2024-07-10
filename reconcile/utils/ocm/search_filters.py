from abc import (
    ABC,
    abstractmethod,
)
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import (
    UTC,
    datetime,
)
from enum import Enum
from typing import (
    Any,
    Optional,
)

import dateparser


@dataclass
class FilterCondition:
    """
    A protocol to be implemented by OCM search filter conditions.
    """

    key: str

    @abstractmethod
    def render(self) -> str:
        """
        Renders the condition into a string that can be used as part of a
        search filter.
        """

    @abstractmethod
    def copy_and_merge(self, other: "FilterCondition") -> "FilterCondition":
        """
        Creates a copy of this condition and merges the other
        condition into it if possible. If merging with the other
        condition is not possible, an InvalidFilterError should be
        raised.
        """


@dataclass
class ListCondition(ABC, FilterCondition):
    """
    A filter condition that represents a list of values. This is used as a
    base class for the list based conditions.
    """

    values: list[Any]

    def copy_and_merge(self, other: "FilterCondition") -> "FilterCondition":
        if not isinstance(other, ListCondition) or not isinstance(self, type(other)):
            raise InvalidFilterError(f"Cannot merge {self} with {other}")
        return type(self)(
            key=self.key,
            values=sorted(set(self.values + other.values)),
        )


@dataclass
class EqCondition(ListCondition):
    """
    A filter condition that represents an equality condition. If the list
    of values contains more than one element, the condition will be rendered
    as an IN condition. If the list contains only one element, the condition
    will be rendered as an equality condition.
    """

    def render(self) -> str:
        if len(self.values) == 1:
            return f"{self.key}='{self._escape_value(self.values[0])}'"
        quoted_values = ",".join(f"'{self._escape_value(x)}'" for x in self.values)
        return f"{self.key} in ({quoted_values})"

    def _escape_value(self, value: Any) -> str:
        return str(value).replace("'", "''")


@dataclass
class LikeCondition(ListCondition):
    """
    A filter condition that represents a LIKE condition. If the value list
    contains more than one element, the condition will be rendered as an OR
    condition of all LIKE expressions. If the list contains only one element,
    the condition will be rendered as a single LIKE expression.
    """

    def render(self) -> str:
        if len(self.values) == 1:
            return f"{self.key} like '{self.values[0]}'"
        quoted_values = " or ".join(f"{self.key} like '{x}'" for x in self.values)
        if len(self.values) > 1:
            return f"({quoted_values})"
        return quoted_values


@dataclass
class FilterObjectCondition(FilterCondition):
    """
    A filter condition that wraps a Filter object. This is used to implement
    AND and OR conditions within the Filter object itself.
    """

    filter: "Filter"

    def copy_and_merge(self, other: "FilterCondition") -> "FilterCondition":
        raise InvalidFilterError("daterange merge not supported")

    def render(self) -> str:
        return f"{self.filter.render()}"


@dataclass
class DateRangeCondition(FilterCondition):
    """
    A filter condition that represents a date range that is either
    fully defined by start and end, or defines at least one bound.
    The start and end bounds can also be defined relative to the time
    when render is called. Any string expression that can be parsed
    by the dateparser library is supported, e.g. "now", "today", "5 days ago"
    """

    start: datetime | str | None
    end: datetime | str | None

    def copy_and_merge(self, other: "FilterCondition") -> "FilterCondition":
        raise InvalidFilterError("daterange merge not supported")

    def render(self) -> str:
        conditions = []
        resolved_start = self.resolve_start()
        resolved_end = self.resolve_end()
        if not resolved_start and not resolved_end:
            raise InvalidFilterError("A date range must have at least one bound.")
        if resolved_start and resolved_end and resolved_end < resolved_start:
            raise InvalidFilterError(
                f"Invalid date range: start={resolved_start.isoformat()} end={resolved_end.isoformat()}"
            )
        if resolved_start:
            conditions.append(f"{self.key} >= '{resolved_start.isoformat()}'")
        if resolved_end:
            conditions.append(f"{self.key} <= '{resolved_end.isoformat()}'")
        return " and ".join(conditions)

    def resolve_start(self) -> datetime | None:
        """
        Resolves the start bound of the date range. If the start bound is a
        string, it is parsed by the dateparser library. If it is already a
        datetime, it is returned.
        """
        return DateRangeCondition._resolve_date(self.start) if self.start else None

    def resolve_end(self) -> datetime | None:
        """
        Resolves the end bound of the date range. If the end bound is a
        string, it is parsed by the dateparser library. If it is already a
        datetime, it is returned."""
        return DateRangeCondition._resolve_date(self.end) if self.end else None

    @staticmethod
    def _resolve_date(date: datetime | str) -> datetime:
        if isinstance(date, datetime):
            return date
        parsed = dateparser.parse(
            date,
            settings={"RELATIVE_BASE": DateRangeCondition.now()},
        )
        if parsed is None:
            raise InvalidFilterError(f"Invalid relative date: {date}")

        return parsed

    @staticmethod
    def now() -> datetime:
        return datetime.now(tz=UTC)


class InvalidFilterError(Exception):
    pass


class InvalidChunkRequest(Exception):
    """
    Is raised for various reasons, when a chunk request on a filter is invalid
    """


class FilterMode(Enum):
    """
    An enum representing the different modes of OCM search filters.
    """

    AND = "and"
    OR = "or"


class Filter:
    """
    A class representing an OCM search filter. It can be used to construct complex
    filters using logical OR (|) and AND (&) operations.
    """

    def __init__(
        self,
        conditions: list[FilterCondition] | None = None,
        mode: FilterMode = FilterMode.AND,
    ):
        self.conditions: list[FilterCondition] = conditions or []
        self.mode = mode

    def condition_by_key(self, key: str) -> FilterCondition | None:
        """
        Returns the condition with the given key, or None if it does not exist.
        """
        return next((c for c in self.conditions if c.key == key), None)

    def copy(self) -> "Filter":
        """
        Create an identical copy of the filter.
        """
        conditions_copy = self.conditions.copy()
        return Filter(conditions_copy, mode=self.mode)

    def copy_and_override(self, condition: FilterCondition) -> "Filter":
        """
        Creates a copy of the filter and add the condition to the copy. If the
        condition already exists, it is overridden.
        """
        copied = self.copy()
        copied.conditions = [c for c in copied.conditions if c.key != condition.key] + [
            condition
        ]
        return copied

    def add_condition(self, condition: FilterCondition) -> "Filter":
        """
        Adds a condition to the filter. If the condition already exists, it is
        merged with the existing condition, if possible. If merging is not possible,
        an InvalidFilterError exception is raised.
        """
        # check if the condition exists already
        existing_condition = self.condition_by_key(condition.key)
        if not existing_condition:
            # if not, we copy the filter and append the condition
            copied = self.copy()
            copied.conditions.append(condition)
            return copied

        # if the condition exists already, we try to merge it
        merged_condition = existing_condition.copy_and_merge(condition)
        return self.copy_and_override(merged_condition)

    def eq(self, key: str, value: str | None) -> "Filter":
        """
        Copies the filter and adds a condition to the copy, that requires
        the given key to be equal to the given value. If the value is None,
        the condition is not added.
        """
        if value:
            return self.is_in(key, [value])
        return self

    def like(self, key: str, value: str | None) -> "Filter":
        """
        Copies the filter and adds a condition to the copy, that requires
        the given key to be similar to the given value based on the % wildcard.
        If the value is None, the condition is not added.
        """
        if value:
            return self.add_condition(LikeCondition(key, [value]))
        return self

    def is_in(self, key: str, values: Iterable[Any] | None) -> "Filter":
        """
        Copies the filter and adds a condition to the copy, that requires
        the given key to be equal to one of the given values. If the values
        are None or empty, the condition is not added.
        """
        if values:
            value_list = values if isinstance(values, list) else list(values)
            value_list.sort()
            return self.add_condition(EqCondition(key, value_list))
        return self

    def before(self, key: str, date: datetime | str | None) -> "Filter":
        """
        Copies the filter and adds a condition to the copy, that requires
        the given key to be before the given date. If the date is None,
        the condition is not added.
        """
        if date:
            return self.add_condition(DateRangeCondition(key, None, date))
        return self

    def after(self, key: str, date: datetime | str | None) -> "Filter":
        """
        Copies the filter and adds a condition to the copy, that requires
        the given key to be after the given date. If the date is None,
        the condition is not added.
        """
        if date:
            return self.add_condition(DateRangeCondition(key, date, None))
        return self

    def between(
        self,
        key: str,
        start: datetime | str | None,
        end: datetime | str | None,
    ) -> "Filter":
        """
        Copies the filter and adds a condition to the copy, that requires
        the given key to be between the given dates. If the dates are None,
        the condition is not added.
        """
        return self.add_condition(DateRangeCondition(key, start, end))

    def chunk_by(
        self, key: str, chunk_size: int, ignore_missing: bool = False
    ) -> list["Filter"]:
        """
        Returns a list of filters, each with a subset of the values of the
        given key. Each subnet has at most chunk_size values. If the key is
        not a list condition, an InvalidChunkRequest exception is raised.

        If ignore_missing is True a chunking request for a key that does not
        exist will be ignored and the original filter will be returned as the
        only element of the chunk list.
        """
        chunked_filters = []
        condition = self.condition_by_key(key)
        if condition and isinstance(condition, ListCondition):
            full_list = condition.values
            for chunk_start_idx in range(0, len(full_list), chunk_size):
                list_chunk = full_list[chunk_start_idx : chunk_start_idx + chunk_size]
                chunked_filters.append(
                    self.copy_and_override(type(condition)(key, list_chunk))
                )
            return chunked_filters

        if ignore_missing:
            return [self]

        raise InvalidChunkRequest(
            f"cannot chunk by {key} because it is not a list condition"
        )

    def render(self) -> str:
        """
        Renders the filter into a string that can be used in the search
        parameter of the OCM API.
        """
        if not self.conditions:
            raise InvalidFilterError("no conditions within filter object")
        rendered_conditions = []
        for condition in sorted(self.conditions, key=lambda c: c.key):
            rendered_conditions.append(condition.render())
        if self.mode == FilterMode.OR:
            concat = " or ".join(rendered_conditions)
            if len(rendered_conditions) > 1:
                return f"({concat})"
            return concat
        if self.mode == FilterMode.AND:
            return " and ".join(rendered_conditions)
        raise InvalidFilterError(f"invalid filter mode: {self.mode}")

    def __and__(self, other: Optional["Filter"]) -> "Filter":
        """
        Returns a new filter that is the logical AND of the current filter
        and the given filter.
        """
        if other:
            # fix here - or & and
            self_conditions: list[FilterCondition] = (
                [FilterObjectCondition(str(id(self)), self)]
                if self.mode != FilterMode.AND
                else self.conditions
            )
            other_conditions: list[FilterCondition] = (
                [FilterObjectCondition(str(id(other)), other)]
                if other.mode != FilterMode.AND
                else other.conditions
            )
            and_filter = Filter(mode=FilterMode.AND)
            for condition in self_conditions + other_conditions:
                and_filter = and_filter.add_condition(condition)
            return and_filter
        return self

    def __or__(self, other: Optional["Filter"]) -> "Filter":
        """
        Returns a new filter that is the logical OR of the current filter
        and the given filter.
        """
        if other:
            self_conditions: list[FilterCondition] = (
                [FilterObjectCondition(str(id(self)), self)]
                if self.mode != FilterMode.OR and len(self.conditions) > 1
                else self.conditions
            )
            other_conditions: list[FilterCondition] = (
                [FilterObjectCondition(str(id(other)), other)]
                if other.mode != FilterMode.OR and len(other.conditions) > 1
                else other.conditions
            )
            return Filter(
                conditions=self_conditions + other_conditions,
                mode=FilterMode.OR,
            )
        return self

    def __str__(self) -> str:
        return self.render()

    def __eq__(self, other: object) -> bool:
        """
        Two filters are considered equal if they render to the same string.
        """
        if not isinstance(other, Filter):
            return False
        return self.render() == other.render()
