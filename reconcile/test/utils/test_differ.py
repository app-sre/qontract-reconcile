from reconcile.utils import differ


def test_diff_with_default_equal():
    current = {"a": 1, "b": 2, "c": 3}
    desired = {"a": 1, "b": 20, "d": 30}

    result = differ.diff(current, desired)

    assert result == differ.DiffResult(
        add={"d": 30},
        delete={"c": 3},
        change={"b": (2, 20)},
    )


def test_diff_with_custom_equal():
    current = {"a": 1, "b": 2, "c": 3}
    desired = {"a": [1], "b": [20], "d": [30]}

    result = differ.diff(current, desired, equal=lambda x, y: x == y[0])

    assert result == differ.DiffResult(
        add={"d": [30]},
        delete={"c": 3},
        change={"b": (2, [20])},
    )
