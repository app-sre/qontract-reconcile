import hashlib
import json
from collections.abc import Iterable
from typing import Any, Optional
from urllib import parse

import jinja2


def json_to_dict(input: str) -> Any:
    """Jinja2 filter to parse JSON strings into dictionaries.
       This becomes useful to access Graphql queries data (labels)
    :param input: json string
    :return: dict with the parsed inputs contents
    """
    data = json.loads(input)
    return data


def urlescape(string: str, safe: str = "/", encoding: Optional[str] = None) -> str:
    """Jinja2 filter that is a simple wrapper around urllib's URL quoting
    functions that takes a string value and makes it safe for use as URL
    components escaping any reserved characters using URL encoding. See:
    urllib.parse.quote() and urllib.parse.quote_plus() for reference.

    :param str string: String value to escape.
    :param str safe: Optional characters that should not be escaped.
    :param encoding: Encoding to apply to the string to be escaped. Defaults
        to UTF-8. Unsupported characters raise a UnicodeEncodeError error.
    :type encoding: typing.Optional[str]
    :returns: A string with reserved characters escaped.
    :rtype: str
    """
    return parse.quote(string, safe=safe, encoding=encoding)


def urlunescape(string: str, encoding: Optional[str] = None) -> str:
    """Jinja2 filter that is a simple wrapper around urllib's URL unquoting
    functions that takes an URL-encoded string value and unescapes it
    replacing any URL-encoded values with their character equivalent. See:
    urllib.parse.unquote() and urllib.parse.unquote_plus() for reference.

    :param str string: String value to unescape.
    :param encoding: Encoding to apply to the string to be unescaped. Defaults
        to UTF-8. Unsupported characters are replaced by placeholder values.
    :type encoding: typing.Optional[str]
    :returns: A string with URL-encoded sequences unescaped.
    :rtype: str
    """
    if encoding is None:
        encoding = "utf-8"
    return parse.unquote(string, encoding=encoding)


def eval_filter(input: str, **kwargs: dict[str, Any]) -> str:
    """Jinja2 filter be used when the string
    is in itself a jinja2 template that must be
    evaluated with kwargs. For example in the case
    of the slo-document expression fields.
    :param input: template string
    :kwargs: variables that will be used to evaluate the
             input string
    :return: rendered string
    """
    return jinja2.Template(input).render(**kwargs)


def hash_list(input: Iterable) -> str:
    """
    Deterministic hash of a list for jinja2 templates.
    The order of the list doesn't matter as it is sorted
    before hashing. Note, that the list elements
    must be flat primitives (no dicts/lists).
    """
    lst = list(input)
    str_lst = []
    for el in lst:
        if isinstance(el, (list, dict)):
            raise RuntimeError(
                f"jinja2 hash_list function received non-primitive value {el}. All values received {lst}"
            )
        str_lst.append(str(el))
    msg = "a"  # keep non-empty for hashing empty list
    msg += "".join(sorted(str_lst))
    m = hashlib.sha256()
    m.update(msg.encode("utf-8"))
    return m.hexdigest()
