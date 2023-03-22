from abc import abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import (
    datetime,
    timezone,
)
from typing import (
    Any,
    Optional,
    Protocol,
    Union,
)

import dateparser


class FilterCondition(Protocol):
    """
    A protocol to be implemented by OCM search filter conditions.
    """

    @abstractmethod
    def render(self, key: str) -> str:
        ...


@dataclass
class StringEqualsCondition:
    """
    string equality OCM search filter condition
    """

    value: str

    def render(self, key: str) -> str:
        escaped = self.value.replace("'", "''")
        return f"{key}='{escaped}'"


@dataclass
class StringLikeCondition:
    """
    string equality OCM search filter condition
    """

    value: str

    def render(self, key: str) -> str:
        return f"{key} like '{self.value}'"


@dataclass
class ListInCondition:

    values: list[Any]

    def render(self, key: str) -> str:
        quoted_values = ",".join(map(lambda x: f"'{x}'", self.values))
        return f"{key} in ({quoted_values})"


@dataclass
class OrCondition:

    filters: list["Filter"]

    def render(self, _: str) -> str:
        conditions = " or ".join(map(lambda f: f.render(), self.filters))
        return f"({conditions})"


@dataclass
class DateRangeCondition:

    start: Optional[Union[datetime, str]]
    end: Optional[Union[datetime, str]]

    def render(self, key: str) -> str:
        conditions = []
        resolved_start = self.resolve_start()
        resolved_end = self.resolve_end()
        if resolved_start and resolved_end and resolved_end < resolved_start:
            raise InvalidFilterError(
                f"Invalid date range: start={resolved_start.isoformat()} end={resolved_end.isoformat()}"
            )
        if resolved_start:
            conditions.append(f"{key} >= '{resolved_start.isoformat()}'")
        if resolved_end:
            conditions.append(f"{key} <= '{resolved_end.isoformat()}'")
        return " and ".join(conditions)

    def resolve_start(self) -> Optional[datetime]:
        return DateRangeCondition.resolve_date(self.start) if self.start else None

    def resolve_end(self) -> Optional[datetime]:
        return DateRangeCondition.resolve_date(self.end) if self.end else None

    @staticmethod
    def resolve_date(date: Union[datetime, str]) -> datetime:
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
        return datetime.now(tz=timezone.utc)


class InvalidFilterError(Exception):
    pass


class InvalidChunkRequest(Exception):
    pass


class Filter:
    def __init__(self, conditions: Optional[dict[str, FilterCondition]] = None):
        self.conditions: dict[str, FilterCondition] = conditions or {}

    def copy(self) -> "Filter":
        conditions_copy = self.conditions.copy()
        return Filter(conditions_copy)

    def add_condition(self, key: str, condition: FilterCondition) -> "Filter":
        copied = self.copy()
        copied.conditions[key] = condition
        return copied

    def eq(self, key: str, value: Optional[str]) -> "Filter":
        if value:
            return self.add_condition(key, StringEqualsCondition(value))
        return self

    def like(self, key: str, value: Optional[str]) -> "Filter":
        if value:
            return self.add_condition(key, StringLikeCondition(value))
        return self

    def is_in(self, key: str, values: Optional[Iterable[Any]]) -> "Filter":
        if values:
            if isinstance(values, list):
                value_list = values
            else:
                value_list = list(values)
            if len(value_list) == 1:
                return self.eq(key, str(value_list[0]))
            value_list.sort()
            return self.add_condition(key, ListInCondition(value_list))
        return self

    def combine(self, filter: Optional["Filter"]) -> "Filter":
        conditions_copy = self.conditions.copy()
        if filter:
            conditions_copy.update(filter.conditions)
        return Filter(conditions_copy)

    def before(self, key: str, date: Optional[Union[datetime, str]]) -> "Filter":
        if date:
            return self.add_condition(key, DateRangeCondition(None, date))
        return self

    def after(self, key: str, date: Optional[Union[datetime, str]]) -> "Filter":
        if date:
            return self.add_condition(key, DateRangeCondition(date, None))
        return self

    def between(
        self,
        key: str,
        start: Optional[Union[datetime, str]],
        end: Optional[Union[datetime, str]],
    ) -> "Filter":
        return self.add_condition(key, DateRangeCondition(start, end))

    def chunk_by(
        self, key: str, chunk_size: int, ignore_missing: bool = False
    ) -> list["Filter"]:
        chunked_filters = []
        condition = self.conditions.get(key)
        if condition and isinstance(condition, ListInCondition):
            full_list = condition.values
            for chunk_start_idx in range(0, len(full_list), chunk_size):
                list_chunk = full_list[chunk_start_idx : chunk_start_idx + chunk_size]
                conditions_copy = self.conditions.copy()
                conditions_copy[key] = ListInCondition(list_chunk)
                chunked_filters.append(Filter(conditions_copy))
            return chunked_filters

        if ignore_missing:
            return [self]

        raise InvalidChunkRequest(
            f"cannot chunk by {key} because it is not a list condition"
        )

    def render(self) -> str:
        if not self.conditions:
            raise InvalidFilterError("no conditions within filter object")
        rendered_conditions = []
        for key in sorted(list(self.conditions.keys())):
            condition = self.conditions[key]
            rendered_conditions.append(condition.render(key))
        return " and ".join(rendered_conditions)

    def __str__(self) -> str:
        return self.render()

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Filter):
            return False
        return self.render() == other.render()


def or_filter(*filters: Filter) -> Filter:
    non_empty_filters = [f for f in filters if len(f.conditions) > 0]
    if not non_empty_filters:
        return Filter()
    if len(non_empty_filters) == 1:
        return non_empty_filters[0].copy()

    condition = OrCondition(non_empty_filters)
    return Filter().add_condition(f"__or_{id(condition)}", condition)
