"""OCM search filter DSL.

Ported from reconcile/utils/ocm/search_filters.py (see ADR-007 - reconcile/ cannot be
imported from qontract_utils). Builds the `search` query string used by OCM's REST API.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

import dateparser

if TYPE_CHECKING:
    from collections.abc import Iterable

ACTIVE_SUBSCRIPTION_STATES = {"Active", "Reserved"}
PRODUCT_ID_OSD = "osd"
PRODUCT_ID_ROSA = "rosa"
OCM_CLUSTER_STATE_READY = "ready"


def _utc_now() -> datetime:
    return datetime.now(UTC)


class InvalidFilterError(Exception):
    pass


class InvalidChunkRequestError(Exception):
    """Raised for various reasons, when a chunk request on a filter is invalid."""


@dataclass
class FilterCondition:
    """A protocol to be implemented by OCM search filter conditions."""

    key: str

    @abstractmethod
    def render(self) -> str:
        """Render the condition into a string usable as part of a search filter."""

    @abstractmethod
    def copy_and_merge(self, other: FilterCondition) -> FilterCondition:
        """Create a copy of this condition, merging in the other condition if possible.

        If merging with the other condition is not possible, raises InvalidFilterError.
        """


@dataclass
class ListCondition(ABC, FilterCondition):
    """A filter condition representing a list of values.

    Base class for the list based conditions.
    """

    values: list[Any]

    def copy_and_merge(self, other: FilterCondition) -> FilterCondition:
        if not isinstance(other, ListCondition) or not isinstance(self, type(other)):
            raise InvalidFilterError(f"Cannot merge {self} with {other}")
        return type(self)(
            key=self.key,
            values=sorted(set(self.values + other.values)),
        )


@dataclass
class EqCondition(ListCondition):
    """An equality condition.

    Rendered as an IN condition when the value list has more than one element,
    otherwise as a plain equality condition.
    """

    def render(self) -> str:
        if len(self.values) == 1:
            return f"{self.key}='{self._escape_value(self.values[0])}'"
        quoted_values = ",".join(f"'{self._escape_value(x)}'" for x in self.values)
        return f"{self.key} in ({quoted_values})"

    @staticmethod
    def _escape_value(value: Any) -> str:
        return str(value).replace("'", "''")


@dataclass
class LikeCondition(ListCondition):
    """A LIKE condition.

    Rendered as an OR of LIKE expressions when the value list has more than
    one element, otherwise as a single LIKE expression.
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
    """A filter condition that wraps a Filter object.

    Used to implement AND and OR conditions within the Filter object itself.
    """

    filter: Filter

    def copy_and_merge(self, other: FilterCondition) -> FilterCondition:
        # self/other are unused (this condition can never be merged), but the
        # signature must match the FilterCondition.copy_and_merge interface.
        _ = self, other
        raise InvalidFilterError("daterange merge not supported")

    def render(self) -> str:
        return f"{self.filter.render()}"


@dataclass
class DateRangeCondition(FilterCondition):
    """A date range condition.

    Fully defined by start and end, or defines at least one bound. The start
    and end bounds can also be defined relative to the time when render is
    called. Any string expression parseable by the dateparser library is
    supported, e.g. "now", "today", "5 days ago".
    """

    start: datetime | str | None
    end: datetime | str | None

    def copy_and_merge(self, other: FilterCondition) -> FilterCondition:
        # self/other are unused (this condition can never be merged), but the
        # signature must match the FilterCondition.copy_and_merge interface.
        _ = self, other
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
        """Resolve the start bound of the date range."""
        return DateRangeCondition._resolve_date(self.start) if self.start else None

    def resolve_end(self) -> datetime | None:
        """Resolve the end bound of the date range."""
        return DateRangeCondition._resolve_date(self.end) if self.end else None

    @staticmethod
    def _resolve_date(date: datetime | str) -> datetime:
        if isinstance(date, datetime):
            return date
        parsed = dateparser.parse(
            date,
            settings={"RELATIVE_BASE": _utc_now()},
        )
        if parsed is None:
            raise InvalidFilterError(f"Invalid relative date: {date}")

        return parsed


class FilterMode(Enum):
    """The different modes of OCM search filters."""

    AND = "and"
    OR = "or"


class Filter:
    """An OCM search filter.

    Can be used to construct complex filters using logical OR (|) and AND (&) operations.
    """

    def __hash__(self) -> int:
        # Filters are mutated via copy-on-write helpers and compared by rendered
        # value (see __eq__) - not meant to be hashed/used as dict keys.
        _ = self
        raise TypeError("Filter is unhashable")

    def __init__(
        self,
        conditions: list[FilterCondition] | None = None,
        mode: FilterMode = FilterMode.AND,
    ) -> None:
        self.conditions: list[FilterCondition] = conditions or []
        self.mode = mode

    def condition_by_key(self, key: str) -> FilterCondition | None:
        """Return the condition with the given key, or None if it does not exist."""
        return next((c for c in self.conditions if c.key == key), None)

    def copy(self) -> Filter:
        """Create an identical copy of the filter."""
        conditions_copy = self.conditions.copy()
        return Filter(conditions_copy, mode=self.mode)

    def copy_and_override(self, condition: FilterCondition) -> Filter:
        """Create a copy of the filter and add/override the condition on the copy."""
        copied = self.copy()
        copied.conditions = [c for c in copied.conditions if c.key != condition.key] + [
            condition
        ]
        return copied

    def add_condition(self, condition: FilterCondition) -> Filter:
        """Add a condition to the filter, merging with an existing one if possible."""
        existing_condition = self.condition_by_key(condition.key)
        if not existing_condition:
            copied = self.copy()
            copied.conditions.append(condition)
            return copied

        merged_condition = existing_condition.copy_and_merge(condition)
        return self.copy_and_override(merged_condition)

    def eq(self, key: str, value: str | None) -> Filter:
        """Add an equality condition. A None value is a no-op."""
        if value:
            return self.is_in(key, [value])
        return self

    def like(self, key: str, value: str | None) -> Filter:
        """Add a LIKE condition (% wildcard). A None value is a no-op."""
        if value:
            return self.add_condition(LikeCondition(key, [value]))
        return self

    def is_in(self, key: str, values: Iterable[Any] | None) -> Filter:
        """Add an IN condition. Empty/None values are a no-op."""
        if values:
            value_list = sorted(values)
            return self.add_condition(EqCondition(key, value_list))
        return self

    def before(self, key: str, date: datetime | str | None) -> Filter:
        """Add a condition requiring the key to be before the given date."""
        if date:
            return self.add_condition(DateRangeCondition(key, None, date))
        return self

    def after(self, key: str, date: datetime | str | None) -> Filter:
        """Add a condition requiring the key to be after the given date."""
        if date:
            return self.add_condition(DateRangeCondition(key, date, None))
        return self

    def between(
        self,
        key: str,
        start: datetime | str | None,
        end: datetime | str | None,
    ) -> Filter:
        """Add a condition requiring the key to be between the given dates."""
        return self.add_condition(DateRangeCondition(key, start, end))

    def chunk_by(
        self, key: str, chunk_size: int, *, ignore_missing: bool = False
    ) -> list[Filter]:
        """Split the filter into chunks of at most chunk_size values for the given key.

        If ignore_missing is True, a chunking request for a key that does not exist
        returns the original filter as the only element of the chunk list.
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

        raise InvalidChunkRequestError(
            f"cannot chunk by {key} because it is not a list condition"
        )

    def render(self) -> str:
        """Render the filter into a string usable in the `search` query param."""
        if not self.conditions:
            raise InvalidFilterError("no conditions within filter object")
        rendered_conditions = [
            condition.render()
            for condition in sorted(self.conditions, key=lambda c: c.key)
        ]
        if self.mode == FilterMode.OR:
            concat = " or ".join(rendered_conditions)
            if len(rendered_conditions) > 1:
                return f"({concat})"
            return concat
        if self.mode == FilterMode.AND:
            return " and ".join(rendered_conditions)
        raise InvalidFilterError(f"invalid filter mode: {self.mode}")

    def __and__(self, other: Filter | None) -> Filter:
        """Return the logical AND of this filter and the given filter."""
        if other:
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

    def __or__(self, other: Filter | None) -> Filter:
        """Return the logical OR of this filter and the given filter."""
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
        """Two filters are equal if they render to the same string."""
        if not isinstance(other, Filter):
            return False
        return self.render() == other.render()


def subscription_label_filter() -> Filter:
    """Return a filter that matches only subscription labels."""
    return Filter().eq("type", "Subscription")


def organization_label_filter() -> Filter:
    """Return a filter that matches only organization labels."""
    return Filter().eq("type", "Organization")


def build_subscription_filter(
    states: set[str] | None = None, *, managed: bool = True
) -> Filter:
    """Build a subscription search filter for the status and managed fields."""
    return Filter().is_in("status", states).eq("managed", str(managed).lower())


def cluster_ready_for_app_interface() -> Filter:
    """Filter for managed OSD/ROSA clusters in ready state."""
    return (
        Filter()
        .eq("managed", "true")
        .eq("state", OCM_CLUSTER_STATE_READY)
        .is_in("product.id", [PRODUCT_ID_OSD, PRODUCT_ID_ROSA])
    )
