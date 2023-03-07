from typing import Optional

import pytest
from jsonpath_ng import (
    Child,
    Fields,
    Index,
    Slice,
    This,
)
from jsonpath_ng.ext import parse
from jsonpath_ng.ext.filter import (
    Expression,
    Filter,
)

from reconcile.utils.jsonpath import (
    apply_constraint_to_path,
    jsonpath_parts,
    narrow_jsonpath_node,
    remove_prefix_from_path,
    sortable_jsonpath_string_repr,
)

#
# test jsonpath splitting
#


def test_jsonpath_parts():
    path = parse("$.a.b.c")
    assert jsonpath_parts(path) == [parse("$"), parse("a"), parse("b"), parse("c")]


def test_jsonpath_parts_root_only():
    path = parse("$")
    assert jsonpath_parts(path) == [parse("$")]


def test_jsonpath_parts_with_index():
    path = parse("a[0]")
    assert jsonpath_parts(path) == [parse("a"), Index(0)]


def test_jsonpath_parts_with_slice_all():
    path = parse("a[*]")
    assert jsonpath_parts(path) == [parse("a"), Slice(None, None, None)]


def test_jsonpath_parts_with_filter():
    path = parse("a.b[?(@.c=='c')].d")
    assert jsonpath_parts(path) == [
        parse("a"),
        parse("b"),
        Filter(expressions=[Expression(Child(This(), Fields("c")), "==", "c")]),
        parse("d"),
    ]


def test_jsonpath_parts_with_filter_ignore():
    path = parse("a.b[?(@.c=='c')].d")
    assert jsonpath_parts(path, ignore_filter=True) == [
        parse("a"),
        parse("b"),
        parse("d"),
    ]


def test_jsonpath_parts_ignore_root():
    path = parse("$.a.b")
    assert jsonpath_parts(path, ignore_root=True) == [
        parse("a"),
        parse("b"),
    ]


def test_jsonpath_parts_without_ignore_root():
    path = parse("$.a.b")
    assert jsonpath_parts(path) == [
        parse("$"),
        parse("a"),
        parse("b"),
    ]


#
# test narrow jsonpath node
#


def test_narrow_jsonpath_node_field_equal():
    assert narrow_jsonpath_node(parse("a"), parse("a")) == parse("a")


def test_narrow_jsonpath_node_field_not_equal():
    assert not narrow_jsonpath_node(parse("a"), parse("b"))


def testnarrow_jsonpath_node_index_equal():
    assert narrow_jsonpath_node(Index(0), Index(0)) == Index(0)


def test_narrow_jsonpath_node_index_slice():
    assert narrow_jsonpath_node(Index(0), Slice(None, None, None)) == Index(0)


def test_narrow_jsonpath_node_slice_index():
    assert narrow_jsonpath_node(Slice(None, None, None), Index(0)) == Index(0)


def test_narrow_jsonpath_node_slice_slice():
    assert narrow_jsonpath_node(
        Slice(None, None, None), Slice(None, None, None)
    ) == Slice(None, None, None)


def test_narrow_jsonpath_node_filter_equal():
    assert narrow_jsonpath_node(
        Filter(expressions=[Expression(Child(This(), Fields("c")), "==", "c")]),
        Filter(expressions=[Expression(Child(This(), Fields("c")), "==", "c")]),
    ) == Filter(expressions=[Expression(Child(This(), Fields("c")), "==", "c")])


def test_narrow_jsonpath_node_filter_not_equal():
    assert (
        narrow_jsonpath_node(
            Filter(expressions=[Expression(Child(This(), Fields("c")), "==", "c")]),
            Filter(expressions=[Expression(Child(This(), Fields("d")), "==", "d")]),
        )
        is None
    )


def test_narrow_jsonpath_node_filter_slice():
    filter = Filter(expressions=[Expression(Child(This(), Fields("c")), "==", "c")])
    assert (
        narrow_jsonpath_node(
            filter,
            Slice(None, None, None),
        )
        == filter
    )


def test_narrow_jsonpath_node_silce_filter():
    filter = Filter(expressions=[Expression(Child(This(), Fields("c")), "==", "c")])
    assert (
        narrow_jsonpath_node(
            Slice(None, None, None),
            filter,
        )
        == filter
    )


def test_narrow_jsonpath_node_index_filter():
    assert narrow_jsonpath_node(
        Index(0),
        Filter(expressions=[Expression(Child(This(), Fields("c")), "==", "c")]),
    ) == Index(0)


def test_narrow_jsonpath_node_filter_index():
    assert narrow_jsonpath_node(
        Filter(expressions=[Expression(Child(This(), Fields("c")), "==", "c")]),
        Index(0),
    ) == Index(0)


def test_narrow_jsonpath_node_field_wildcard():
    assert narrow_jsonpath_node(parse("a"), parse("*")) == parse("a")


def test_narrow_jsonpath_node_wildcard_field():
    assert narrow_jsonpath_node(parse("*"), parse("a")) == parse("a")


def test_narrow_jsonpath_node_wildcard_wildcard():
    assert narrow_jsonpath_node(parse("*"), parse("*")) == parse("*")


#
# narrow jsonpath expression
#


def test_apply_constraint_to_path_equal():
    assert apply_constraint_to_path(parse("a.b.c"), parse("a.b.c")) == parse("a.b.c")


def test_apply_constraint_to_longer_path():
    assert apply_constraint_to_path(parse("a.b[*].c.f"), parse("a.b[0].c")) == parse(
        "a.b[0].c.f"
    )


def test_apply_constraint_to_shorter_path():
    assert apply_constraint_to_path(parse("a.b[*]"), parse("a.b[0].c")) == parse(
        "a.b[0]"
    )


def test_apply_constraint_to_unrelated_path():
    assert not apply_constraint_to_path(parse("a.b[*]"), parse("d.e[0].f"))


def test_apply_incompatible_constraint_to_path():
    assert apply_constraint_to_path(parse("a.b[0].f"), parse("a.b[1].c")) == parse(
        "a.b[0].f"
    )


def test_apply_partially_incompatible_constraint_to_path():
    assert apply_constraint_to_path(
        parse("a.b[*].c[0].d"), parse("a.b[1].c[1]")
    ) == parse("a.b[1].c[0].d")


def test_apply_field_constraint_to_wildcard_path():
    assert apply_constraint_to_path(parse("a.*.c"), parse("a.b.c.d")) == parse("a.b.c")


#
# test sortable jsonpath representation
#


@pytest.mark.parametrize(
    "jsonpath, sortable_jsonpath",
    [
        ("a.b[0].c", "a.b.[00000].c"),
        ("a.b[10].c", "a.b.[00010].c"),
        ("[10]", "[00010]"),
        ("a.[10][*]", "a.[00010].*"),
    ],
)
def test_sortable_jsonpath_string_repr(jsonpath: str, sortable_jsonpath: str):
    assert sortable_jsonpath_string_repr(parse(jsonpath), 5) == sortable_jsonpath


#
# test remove prefix from path
#


@pytest.mark.parametrize(
    "path, prefix, expected",
    [
        # simple prefix
        ("a.b.c.d.e", "a.b.c", "d.e"),
        # the path is has not the defined prefix
        ("a.b.c.d.e", "f.g", None),
        # path and prefix are the same
        ("a.b.c.d.e", "a.b.c.d.e", None),
        # path with index
        ("a.b[1].c", "a", "b[1].c"),
        # path with index after the prefix
        ("a.b[1].c", "a.b", "[1].c"),
        # prefix is root
        ("a.b", "$", "a.b"),
        # prefix and path are root
        ("$", "$", None),
    ],
)
def test_remove_prefix_from_path(path: str, prefix: str, expected: Optional[str]):
    expected_path = parse(expected) if expected else None
    assert remove_prefix_from_path(parse(path), parse(prefix)) == expected_path
