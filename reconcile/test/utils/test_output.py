from reconcile.utils.output import format_table


def test_format_table_simple() -> None:
    output = format_table(
        [
            {"a": "a1", "b": {"b": "b1"}, "c": ["1", "2"]},
            {"a": "a2", "b": {"b": "b2"}, "c": ["1", "2"]},
            {"a": "a3", "b": {"b": "b3"}, "c": ["1", "2"]},
        ],
        ["a", "b", "b.b", "c"],
        "simple",
    )

    print(repr(output))

    assert (
        output
        == "A    B            B.B    C\n---  -----------  -----  ---\na1   {'b': 'b1'}  b1     1\n                         2\na2   {'b': 'b2'}  b2     1\n                         2\na3   {'b': 'b3'}  b3     1\n                         2"
    )


def test_format_table_github() -> None:
    output = format_table(
        [
            {"a": "a1", "b": {"b": "b1"}, "c": ["1", "2"]},
            {"a": "a2", "b": {"b": "b2"}, "c": ["1", "2"]},
            {"a": "a3", "b": {"b": "b3"}, "c": ["1", "2"]},
        ],
        ["a", "b", "b.b", "c"],
        "github",
    )

    print(repr(output))

    assert (
        output
        == "| A   | B           | B.B   | C        |\n|-----|-------------|-------|----------|\n| a1  | {'b': 'b1'} | b1    | 1<br />2 |\n| a2  | {'b': 'b2'} | b2    | 1<br />2 |\n| a3  | {'b': 'b3'} | b3    | 1<br />2 |"
    )


def test_format_table_missing_column_field() -> None:
    output = format_table(
        [
            {"a": "a1", "b": {"b": "b1"}, "c": ["1", "2"]},
            {"a": "a2", "b": {"b": "b2"}, "c": ["1", "2"]},
            {"a": "a3", "b": {"b": "b3"}, "c": ["1", "2"]},
        ],
        ["non_existant"],
    )

    print(repr(output))

    assert output == "NON_EXISTANT\n--------------\n\n\n"
