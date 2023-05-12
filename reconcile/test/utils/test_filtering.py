from typing import (
    Any,
    Optional,
)

from reconcile.utils.filtering import remove_none_values_from_dict


def test_remove_none_values_from_dict_all_none() -> None:
    assert remove_none_values_from_dict({"a": None, "b": None}) == {}


def test_remove_empty_values_from_dict_dont_remove_not_none() -> None:
    a_dict: dict[str, Optional[Any]] = {
        "a": "",
        "b": [],
        "c": {},
        "d": 0,
        "e": "str",
        "f": False,
    }
    filtered_dict = remove_none_values_from_dict(a_dict)
    assert filtered_dict == a_dict


def test_remove_none_values_from_empty_dict() -> None:
    assert remove_none_values_from_dict({}) == {}
