from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any
from urllib import parse

import jinja2
import jsonpath_ng
import jsonpath_ng.ext.filter
import yaml

from reconcile.utils.jsonpath import jsonpath_parts, parse_jsonpath

if TYPE_CHECKING:
    from collections.abc import Iterable


def json_to_dict(input: str) -> Any:
    """Jinja2 filter to parse JSON strings into dictionaries.
       This becomes useful to access Graphql queries data (labels)
    :param input: json string
    :return: dict with the parsed inputs contents
    """
    data = json.loads(input)
    return data


def yaml_to_dict(input: str) -> Any:
    """Jinja2 filter to parse YAML strings into dictionaries.
    :param input: yaml string
    :return: dict with the parsed inputs contents
    """
    data = yaml.safe_load(input)
    return data


def urlescape(string: str, safe: str = "/", encoding: str | None = None) -> str:
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


def urlunescape(string: str, encoding: str | None = None) -> str:
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
        if isinstance(el, list | dict):
            raise TypeError(
                f"jinja2 hash_list function received non-primitive value {el}. All values received {lst}"
            )
        str_lst.append(str(el))
    msg = "a"  # keep non-empty for hashing empty list
    msg += "".join(sorted(str_lst))
    m = hashlib.sha256()
    m.update(msg.encode("utf-8"))
    return m.hexdigest()


class _LegacyIndex(jsonpath_ng.Index):
    """
    Like `jsonpath_ng.Index`, but also indexes into a scalar string the way
    Python does. jsonpath_ng (>=1.12) restricts integer indices to arrays
    (RFC 9535: a JSON string isn't an array); Jinja2 templates may rely on
    the previous, more permissive behavior, e.g. "a"[0] == "a".
    """

    def find(self, datum: Any) -> list[jsonpath_ng.DatumInContext]:
        wrapped = jsonpath_ng.DatumInContext.wrap(datum)
        if isinstance(wrapped.value, str):
            return [
                jsonpath_ng.DatumInContext(
                    wrapped.value[i], path=jsonpath_ng.Index(i), context=wrapped
                )
                for i in self.indices
                if -len(wrapped.value) <= i < len(wrapped.value)
            ]
        return super().find(datum)


class _LegacyWildcard(jsonpath_ng.Slice):
    """
    Like `jsonpath_ng.Slice`, but a dict or any other non-array scalar
    (str/int/float/bool) matches a slice/wildcard as if it were a
    single-element array, exactly as jsonpath_ng 1.8.0's `Slice.find` did
    (`if isinstance(value, dict) or isinstance(value, (int, float, str,
    bool)): return self.find(DatumInContext([value], path=.., context=..))`).
    jsonpath_ng (>=~1.9) instead restricts slices/wildcards to actual arrays
    (RFC 9535); Jinja2 templates may rely on the previous behavior, e.g.
    extract_jsonpath("abc", "[*]") == ["abc"].
    """

    _SCALAR_TYPES = (dict, int, float, str, bool)

    def find(self, datum: Any) -> list[jsonpath_ng.DatumInContext]:
        wrapped = jsonpath_ng.DatumInContext.wrap(datum)
        if isinstance(wrapped.value, self._SCALAR_TYPES):
            return self.find(
                jsonpath_ng.DatumInContext(
                    [wrapped.value], path=wrapped.path, context=wrapped.context
                )
            )
        return super().find(datum)


_BINARY_NODE_TYPES = (
    jsonpath_ng.Child,
    jsonpath_ng.Descendants,
    jsonpath_ng.Where,
    jsonpath_ng.WhereNot,
)

_LOGICAL_NODE_TYPES = (
    jsonpath_ng.ext.filter.And,
    jsonpath_ng.ext.filter.Or,
)


def _with_legacy_semantics(node: jsonpath_ng.JSONPath) -> jsonpath_ng.JSONPath:
    """
    Rebuild `node`, substituting every Index/wildcard-Slice leaf for a
    variant that preserves jsonpath_ng's previous behavior on scalar values
    (see _LegacyIndex/_LegacyWildcard above). Every jsonpath_ng binary node
    in `_BINARY_NODE_TYPES` composes find() purely through its own
    `left`/`right` operands (all share the same `__init__(self, left,
    right)` shape), so recursing generically through any of them - rather
    than special-casing each one's own find() logic - is enough to take
    effect at any nesting depth and through any combinator, e.g. "[0]",
    "name[0]", "$[0]", and "items..[0]". A filter expression, e.g.
    "items[?@.name[0]=='a']", is not part of that binary tree: its Index
    nodes live inside Filter.expressions/Expression.target/Expression.value
    and And/Or.operands instead, so those are rebuilt the same way. Leaf
    nodes (Fields, Root, ...) aren't handled by any branch and pass through
    unchanged.
    """
    if isinstance(node, jsonpath_ng.Index) and not isinstance(node, _LegacyIndex):
        return _LegacyIndex(*node.indices)
    if isinstance(node, jsonpath_ng.Slice) and not isinstance(node, _LegacyWildcard):
        return _LegacyWildcard(node.start, node.end, node.step)
    if isinstance(node, _BINARY_NODE_TYPES):
        return type(node)(
            _with_legacy_semantics(node.left), _with_legacy_semantics(node.right)
        )
    if isinstance(node, jsonpath_ng.ext.filter.Filter):
        return jsonpath_ng.ext.filter.Filter([
            _with_legacy_semantics(expression) for expression in node.expressions
        ])
    if isinstance(node, jsonpath_ng.ext.filter.Expression):
        value = (
            _with_legacy_semantics(node.value)
            if isinstance(node.value, jsonpath_ng.JSONPath)
            else node.value
        )
        return jsonpath_ng.ext.filter.Expression(
            _with_legacy_semantics(node.target), node.op, value
        )
    if isinstance(node, _LOGICAL_NODE_TYPES):
        return type(node)(_with_legacy_semantics(operand) for operand in node.operands)
    return node


def _find_jsonpath(input: Any, jsonpath: str | None) -> Any:
    assert jsonpath is not None and len(jsonpath) > 0
    return _with_legacy_semantics(parse_jsonpath(jsonpath)).find(input)


def extract_jsonpath(input: Any, jsonpath: str) -> Any:
    """
    Extracts data from the input using jsonpath.
    The result is a list of matching elements.
    The list will be empty if nothing matches.
    """
    return [i.value for i in _find_jsonpath(input, jsonpath)]


def matches_jsonpath(input: Any, jsonpath: str | None) -> bool:
    """
    Returns True if the input matches the provided jsonpath
    """
    return len(_find_jsonpath(input, jsonpath)) > 0


def _jsonpath_to_pointer(path: jsonpath_ng.JSONPath) -> str:
    """
    Converts a jsonpath_ng path to a rfc6901 pointer
    (https://www.rfc-editor.org/rfc/rfc6901), e.g. "items.[2].type" -> "/items/2/type"
    """
    segments: list[str] = []
    for part in jsonpath_parts(path, ignore_root=True):
        if isinstance(part, jsonpath_ng.Fields):
            # RFC 6901: escape ~ as ~0 and / as ~1, in that order, before joining
            segments.extend(
                str(f).replace("~", "~0").replace("/", "~1") for f in part.fields
            )
        elif isinstance(part, jsonpath_ng.Index):
            segments.extend(str(i) for i in part.indices)
    return "/" + "/".join(segments)


def json_pointers(input: Any, jsonpath: str) -> list[str]:
    """
    Finds the RFC6901 JSON pointers of the input elements matching the given jsonpath
    """
    return [_jsonpath_to_pointer(i.full_path) for i in _find_jsonpath(input, jsonpath)]


def str_format(value: str, format: str) -> str:
    return format % value
