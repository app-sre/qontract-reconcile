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
)

#
# eq and is_in
#


def test_search_filter_eq():
    assert "some_field='some_value'" == Filter().eq("some_field", "some_value").render()


def test_search_filter_eq_none_value():
    with pytest.raises(InvalidFilterError):
        Filter().eq("some_field", None).render()


def test_search_filter_is_in():
    assert (
        "some_field in ('a','b','c')"
        == Filter().is_in("some_field", ["a", "b", "c"]).render()
    )


def test_search_filter_is_in_no_items():
    with pytest.raises(InvalidFilterError):
        Filter().is_in("some_field", None).render()
    with pytest.raises(InvalidFilterError):
        Filter().is_in("some_field", []).render()


def test_search_filter_is_in_one_items():
    assert Filter().is_in("some_field", [1]).render() == "some_field='1'"


def test_search_filter_merge_eq_eq_and():
    f1 = Filter().eq("some_field", "a")
    f2 = Filter().eq("some_field", "b")
    assert "some_field in ('a','b')" == (f1 & f2).render()


def test_search_filter_merge_eq_eq_chain():
    f = Filter().eq("some_field", "a").eq("some_field", "b")
    assert "some_field in ('a','b')" == f.render()


def test_search_filter_merge_eq_is_in_and():
    f1 = Filter().eq("some_field", "a")
    f2 = Filter().is_in("some_field", ["b", "c"])
    assert "some_field in ('a','b','c')" == (f1 & f2).render()


def test_search_filter_merge_eq_is_in_chain():
    f = Filter().eq("some_field", "a").is_in("some_field", ["b", "c"])
    assert "some_field in ('a','b','c')" == f.render()


def test_search_filter_merge_eq_is_in_dedup():
    f1 = Filter().eq("some_field", "a")
    f2 = Filter().is_in("some_field", ["a", "b", "c"])
    assert "some_field in ('a','b','c')" == (f1 & f2).render()


#
# like
#


def test_search_filter_like():
    assert (
        "some_field like 'some_value%'"
        == Filter().like("some_field", "some_value%").render()
    )


def test_search_filter_like_none_value():
    with pytest.raises(InvalidFilterError):
        Filter().like("some_field", None).render()


def test_search_filter_merge_like_merge():
    f1 = Filter().like("some_field", "a%")
    f2 = Filter().like("some_field", "b%")
    assert "(some_field like 'a%' or some_field like 'b%')" == (f1 & f2).render()


def test_search_filter_merge_like_chain():
    f = Filter().like("some_field", "a%").like("some_field", "b%")
    assert "(some_field like 'a%' or some_field like 'b%')" == f.render()


#
# date
#


def test_search_filter_before():
    assert (
        Filter()
        .before("timestamp", datetime(2020, 1, 1, 0, 0, 0, 0, tzinfo=timezone.utc))
        .render()
        == "timestamp <= '2020-01-01T00:00:00+00:00'"
    )


def test_search_filter_before_relative(mocker: MockerFixture):
    now_mock = mocker.patch.object(DateRangeCondition, "now")
    now_mock.return_value = datetime(2020, 1, 2, 0, 0, 0, 0, tzinfo=timezone.utc)

    assert (
        Filter().before("timestamp", "1 day ago").render()
        == "timestamp <= '2020-01-01T00:00:00'"
    )


def test_search_filter_after():
    assert (
        Filter()
        .after("timestamp", datetime(2020, 1, 1, 0, 0, 0, 0, tzinfo=timezone.utc))
        .render()
        == "timestamp >= '2020-01-01T00:00:00+00:00'"
    )


def test_search_filter_after_relative(mocker: MockerFixture):
    now_mock = mocker.patch.object(DateRangeCondition, "now")
    now_mock.return_value = datetime(2020, 1, 2, 0, 0, 0, 0, tzinfo=timezone.utc)

    assert (
        Filter().after("timestamp", "1 day ago").render()
        == "timestamp >= '2020-01-01T00:00:00'"
    )


def test_search_filter_between():
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


def test_search_filter_between_end_before_start():
    with pytest.raises(InvalidFilterError):
        Filter().between(
            "timestamp",
            datetime(2020, 1, 2, 0, 0, 0, 0, tzinfo=timezone.utc),
            datetime(2020, 1, 1, 0, 0, 0, 0, tzinfo=timezone.utc),
        ).render()


def test_search_filter_invalid_relative_date():
    with pytest.raises(InvalidFilterError):
        Filter().after("timestamp", "5 glas of milk").render()


#
# chunking
#


def test_search_filter_chunk_is_in():
    list_filter = Filter().is_in("some_field", ["a", "b", "c", "d", "e"])
    chunks = list_filter.chunk_by("some_field", chunk_size=2)
    assert len(chunks) == 3

    assert {
        "some_field in ('a','b')",
        "some_field in ('c','d')",
        "some_field='e'",
    } == {c.render() for c in chunks}


def test_search_filter_chunk_eq():
    f = Filter().eq("some_field", "some_value")
    chunks = f.chunk_by("some_field", chunk_size=2)
    assert len(chunks) == 1
    assert f.render() == chunks[0].render()


def test_search_filter_chunk_like():
    f = (
        Filter()
        .like("some_field", "a%")
        .like("some_field", "b%")
        .like("some_field", "c%")
    )
    chunks = f.chunk_by("some_field", chunk_size=2)
    assert len(chunks) == 2
    assert {
        "(some_field like 'a%' or some_field like 'b%')",
        "some_field like 'c%'",
    } == {c.render() for c in chunks}


def test_search_filter_chunk_unknown_field():
    list_filter = Filter().is_in("some_field", ["a", "b"])
    with pytest.raises(InvalidChunkRequest):
        list_filter.chunk_by("some_other_field", chunk_size=2)


def test_search_filter_chunk_ignore_missing():
    list_filter = Filter().is_in("some_field", ["a", "b"])
    assert [list_filter] == list_filter.chunk_by(
        "some_other_field",
        chunk_size=2,
        ignore_missing=True,
    )


#
# combination tests
#


def test_search_filter_chain_conditions():
    multi_filter = (
        Filter().eq("some_field", "some_value").is_in("some_list", ["a", "b"])
    )
    assert "some_field='some_value' and some_list in ('a','b')" == multi_filter.render()


def test_search_filter_combine_different_conditions():
    f1 = Filter().eq("eq_field_1", "some_value")
    f2 = Filter().eq("eq_field_2", "some_other_value")
    f3 = Filter().like("like_field", "a%")
    f4 = Filter().like("like_field", "b%")
    combined = f1 & f2 & f3 & f4
    assert (
        "eq_field_1='some_value' and eq_field_2='some_other_value' and "
        + "(like_field like 'a%' or like_field like 'b%')"
        == combined.render()
    )


#
# immutability
#


def test_search_filter_immutability():
    eq_filter = Filter().eq("some_field", "some_value")
    derive_filter = eq_filter.eq("some_other_field", "some_other_value")
    assert eq_filter != derive_filter
    assert "some_field='some_value'" == eq_filter.render()


#
# or
#


def test_search_filter_or():
    f1 = Filter().eq("some_field", "some_value")
    f2 = Filter().eq("some_other_field", "some_other_value")
    or_condition = f1 | f2
    assert (
        "(some_field='some_value' or some_other_field='some_other_value')"
        == or_condition.render()
    )


def test_search_filter_combine_and_or():
    f1 = Filter().eq("some_field", "some_value")
    f2 = Filter().eq("some_other_field", "some_other_value")
    or_condition = f1 | f2
    combined_filter = Filter().eq("eq_field", "eq_value") & or_condition
    assert (
        "(some_field='some_value' or some_other_field='some_other_value') and eq_field='eq_value'"
        == combined_filter.render()
    )


def test_search_filter_combine_or_and():
    f1 = Filter().eq("some_field", "some_value")
    f2 = Filter().eq("some_other_field", "some_other_value")
    or_condition = f1 | f2
    combined_filter = or_condition & Filter().eq("eq_field", "eq_value")
    assert (
        "(some_field='some_value' or some_other_field='some_other_value') and eq_field='eq_value'"
        == combined_filter.render()
    )


#
# filter term optimizations
#


def test_search_filter_eliminate_empty_or_conditions():
    f1 = (
        Filter().is_in("some_list_field", [])
        | Filter().eq("some_field", "some_value")
        | Filter()
    )
    assert f1.render() == "some_field='some_value'"

    f2 = (
        Filter().is_in("some_list_field", [1, 2])
        | Filter().eq("some_field", "some_value")
        | Filter()
    )
    assert f2.render() == "(some_field='some_value' or some_list_field in ('1','2'))"


def test_search_filter_dont_render_brackets_when_one_condition():
    f = Filter().is_in("some_list_field", [1, 2]) | Filter()
    assert f.render() == "some_list_field in ('1','2')"


def test_search_filter_simplify_multiple_or_conditions():
    or_condition = (
        Filter().is_in("some_list_field", [1, 2])
        | Filter().eq("some_field", "some_value")
        | Filter().eq("other_field", "other_value")
    )
    eq_condition = Filter().eq("eq_field", "eq_value")
    combined = or_condition & eq_condition
    assert (
        combined.render()
        == "(other_field='other_value' or some_field='some_value' or some_list_field in ('1','2')) and eq_field='eq_value'"
    )


#
# misc
#


def test_search_filter_escape_quotes():
    assert (
        Filter().eq("some_field", "contains'quote").render()
        == "some_field='contains''quote'"
    )

    assert (
        Filter().eq("some_field", "contains''quote").render()
        == "some_field='contains''''quote'"
    )


def test_search_filter_equals():
    f1 = Filter().eq("some_field", "a")
    f2 = Filter().eq("some_field", "a")
    assert f1 == f2

    f3 = Filter().eq("some_field", "a").is_in("some_field", ["b", "c"])
    f4 = Filter().eq("some_field", "a").eq("some_field", "c").eq("some_field", "b")
    assert f3 == f4
