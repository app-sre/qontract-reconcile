from datetime import (
    datetime,
    timezone,
)

import pytest
from pytest_mock import MockerFixture

from reconcile.utils.ocm.search_filters import (
    DateRangeCondition,
    Filter,
    InvalidChunkRequest,
    InvalidFilterError,
    or_filter,
)


def test_ocm_search_filter_eq():
    assert "some_field='some_value'" == Filter().eq("some_field", "some_value").render()


def test_ocm_search_filter_eq_none_value():
    with pytest.raises(InvalidFilterError):
        Filter().eq("some_field", None).render()


def test_ocm_search_filter_like():
    assert (
        "some_field like 'some_value%'"
        == Filter().like("some_field", "some_value%").render()
    )


def test_ocm_search_filter_like_none_value():
    with pytest.raises(InvalidFilterError):
        Filter().like("some_field", None).render()


def test_ocm_search_filter_is_in():
    assert (
        "some_field in ('a','b','c')"
        == Filter().is_in("some_field", ["a", "b", "c"]).render()
    )


def test_ocm_search_filter_is_in_no_items():
    with pytest.raises(InvalidFilterError):
        Filter().is_in("some_field", None).render()
    with pytest.raises(InvalidFilterError):
        Filter().is_in("some_field", []).render()


def test_ocm_search_filter_is_in_one_items():
    assert Filter().is_in("some_field", [1]).render() == "some_field='1'"


def test_ocm_search_filter_chunk_is_in():
    list_filter = Filter().is_in("some_field", ["a", "b", "c", "d", "e"])
    chunks = list_filter.chunk_by("some_field", chunk_size=2)
    assert len(chunks) == 3

    assert {
        "some_field in ('a','b')",
        "some_field in ('c','d')",
        "some_field in ('e')",
    } == {c.render() for c in chunks}


def test_ocm_search_filter_chunk_is_in_not_a_list():
    eq_filter = Filter().eq("some_field", "some_value")
    with pytest.raises(InvalidChunkRequest):
        eq_filter.chunk_by("some_field", chunk_size=2)


def test_ocm_search_filter_chunk_is_in_unknown_field():
    list_filter = Filter().is_in("some_field", ["a", "b"])
    with pytest.raises(InvalidChunkRequest):
        list_filter.chunk_by("some_other_field", chunk_size=2)


def test_ocm_search_filter_chunk_is_if_available():
    list_filter = Filter().is_in("some_field", ["a", "b", "c", "d", "e"])
    chunks = list_filter.chunk_by(
        "some_field",
        chunk_size=2,
        ignore_missing=True,
    )
    assert len(chunks) == 3

    assert {
        "some_field in ('a','b')",
        "some_field in ('c','d')",
        "some_field in ('e')",
    } == {c.render() for c in chunks}


def test_ocm_search_filter_chunk_if_available_is_in_not_a_list():
    eq_filter = Filter().eq("some_field", "some_value")
    assert [eq_filter] == eq_filter.chunk_by(
        "some_field",
        chunk_size=2,
        ignore_missing=True,
    )


def test_ocm_search_filter_chunk_if_available_is_in_unknown_field():
    list_filter = Filter().is_in("some_field", ["a", "b"])
    assert [list_filter] == list_filter.chunk_by(
        "some_other_field",
        chunk_size=2,
        ignore_missing=True,
    )


def test_ocm_search_filter_multiple_conditions():
    multi_filter = (
        Filter().eq("some_field", "some_value").is_in("some_list", ["a", "b"])
    )
    assert "some_field='some_value' and some_list in ('a','b')" == multi_filter.render()


def test_ocm_search_filter_immutability():
    eq_filter = Filter().eq("some_field", "some_value")
    derive_filter = eq_filter.eq("some_other_field", "some_other_value")
    assert eq_filter != derive_filter
    assert "some_field='some_value'" == eq_filter.render()


def test_ocm_search_filter_combine():
    eq_filter = Filter().eq("some_field", "some_value")
    another_filter = Filter().eq("some_other_field", "some_other_value")
    combined = eq_filter.combine(another_filter)
    assert (
        "some_field='some_value' and some_other_field='some_other_value'"
        == combined.render()
    )


def test_ocm_search_filter_combine_with_none():
    eq_filter = Filter().eq("some_field", "some_value")
    combined = eq_filter.combine(None)
    assert id(eq_filter) != id(combined)  # object identity is still different
    assert "some_field='some_value'" == combined.render()


def test_ocm_search_filter_or():
    or_condition = or_filter(
        Filter().eq("some_field", "some_value"),
        Filter().eq("some_other_field", "some_other_value"),
    )
    assert (
        "(some_field='some_value' or some_other_field='some_other_value')"
        == or_condition.render()
    )


def test_ocm_search_filter_or_combine():
    or_condition = or_filter(
        Filter().eq("some_field", "some_value"),
        Filter().eq("some_other_field", "some_other_value"),
    )
    combined_filter = Filter().eq("eq_field", "eq_value").combine(or_condition)
    assert (
        "(some_field='some_value' or some_other_field='some_other_value') and eq_field='eq_value'"
        == combined_filter.render()
    )


def test_ocm_search_filter_eliminate_empty_or_conditions():
    assert (
        or_filter(
            Filter().is_in("some_list_field", []),
            Filter().eq("some_field", "some_value"),
            Filter(),
        ).render()
        == "some_field='some_value'"
    )

    assert (
        or_filter(
            Filter().is_in("some_list_field", [1, 2]),
            Filter().eq("some_field", "some_value"),
            Filter(),
        ).render()
        == "(some_list_field in ('1','2') or some_field='some_value')"
    )


def test_ocm_search_filter_before():
    assert (
        Filter()
        .before("timestamp", datetime(2020, 1, 1, 0, 0, 0, 0, tzinfo=timezone.utc))
        .render()
        == "timestamp <= '2020-01-01T00:00:00+00:00'"
    )


def test_ocm_search_filter_before_relative(mocker: MockerFixture):
    now_mock = mocker.patch.object(DateRangeCondition, "now")
    now_mock.return_value = datetime(2020, 1, 2, 0, 0, 0, 0, tzinfo=timezone.utc)

    assert (
        Filter().before("timestamp", "1 day ago").render()
        == "timestamp <= '2020-01-01T00:00:00'"
    )


def test_ocm_search_filter_after():
    assert (
        Filter()
        .after("timestamp", datetime(2020, 1, 1, 0, 0, 0, 0, tzinfo=timezone.utc))
        .render()
        == "timestamp >= '2020-01-01T00:00:00+00:00'"
    )


def test_ocm_search_filter_after_relative(mocker: MockerFixture):
    now_mock = mocker.patch.object(DateRangeCondition, "now")
    now_mock.return_value = datetime(2020, 1, 2, 0, 0, 0, 0, tzinfo=timezone.utc)

    assert (
        Filter().after("timestamp", "1 day ago").render()
        == "timestamp >= '2020-01-01T00:00:00'"
    )


def test_ocm_search_filter_between():
    assert (
        Filter()
        .between(
            "timestamp",
            datetime(2020, 1, 1, 0, 0, 0, 0, tzinfo=timezone.utc),
            datetime(2020, 1, 2, 0, 0, 0, 0, tzinfo=timezone.utc),
        )
        .render()
        == "timestamp >= '2020-01-01T00:00:00+00:00' and timestamp <= '2020-01-02T00:00:00+00:00'"
    )


def test_ocm_search_filter_between_end_before_start():
    with pytest.raises(InvalidFilterError):
        Filter().between(
            "timestamp",
            datetime(2020, 1, 2, 0, 0, 0, 0, tzinfo=timezone.utc),
            datetime(2020, 1, 1, 0, 0, 0, 0, tzinfo=timezone.utc),
        ).render()


def test_ocm_search_filter_invalid_relative_date():
    with pytest.raises(InvalidFilterError):
        Filter().after("timestamp", "5 glas of milk").render()


def test_ocm_search_filter_escape_quotes():
    assert (
        Filter().eq("some_field", "contains'quote").render()
        == "some_field='contains''quote'"
    )

    assert (
        Filter().eq("some_field", "contains''quote").render()
        == "some_field='contains''''quote'"
    )


def test_ocm_search_filter_equals():
    assert Filter().eq("some_field", "some_value") == Filter().eq(
        "some_field", "some_value"
    )
