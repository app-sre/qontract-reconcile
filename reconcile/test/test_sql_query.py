import pytest

from reconcile.sql_query import split_long_query


@pytest.mark.parametrize(
    "q, size, excepted",
    [
        ("test", 1, ["t", "e", "s", "t"]),
        (
            "this is a longer string",
            3,
            ["thi", "s i", "s a", " lo", "nge", "r s", "tri", "ng"],
        ),
        ("testtest", 100, ["testtest"]),
    ],
)
def test_split_long_query(q, size, excepted):
    assert split_long_query(q, size) == excepted
