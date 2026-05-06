import datetime
import json
import os
import threading
from collections.abc import Mapping
from functools import cache
from typing import Any, Self

import jinja2
from github import Github
from jinja2.sandbox import SandboxedEnvironment
from pydantic import BaseModel
from sretoolbox.utils import retry

from reconcile import queries
from reconcile.checkpoint import url_makes_sense
from reconcile.github_org import get_default_config
from reconcile.utils import gql
from reconcile.utils.aws_api import AWSApi
from reconcile.utils.datetime_util import utc_now
from reconcile.utils.github_api import GithubRepositoryApi
from reconcile.utils.helpers import flatten
from reconcile.utils.jinja2.extensions import B64EncodeExtension, RaiseErrorExtension
from reconcile.utils.jinja2.filters import (
    eval_filter,
    extract_jsonpath,
    hash_list,
    json_pointers,
    json_to_dict,
    matches_jsonpath,
    str_format,
    urlescape,
    urlunescape,
    yaml_to_dict,
)
from reconcile.utils.secret_reader import (
    SecretNotFoundError,
    SecretReader,
    SecretReaderBase,
)
from reconcile.utils.sloth import generate_sloth_rules


class Jinja2TemplateError(Exception):
    def __init__(self, msg: Any):
        super().__init__("error processing jinja2 template: " + str(msg))


class TemplateRenderOptions(BaseModel, frozen=True):
    trim_blocks: bool
    lstrip_blocks: bool
    keep_trailing_newline: bool

    @classmethod
    def create(
        cls,
        trim_blocks: bool | None = None,
        lstrip_blocks: bool | None = None,
        keep_trailing_newline: bool | None = None,
    ) -> Self:
        return cls(
            trim_blocks=trim_blocks or False,
            lstrip_blocks=lstrip_blocks or False,
            keep_trailing_newline=keep_trailing_newline or False,
        )


@cache
def compile_jinja2_template(
    body: str,
    extra_curly: bool = False,
    template_render_options: TemplateRenderOptions | None = None,
) -> Any:
    if not template_render_options:
        template_render_options = TemplateRenderOptions.create()
    env: dict[str, Any] = template_render_options.model_dump()
    if extra_curly:
        env.update({
            "block_start_string": "{{%",
            "block_end_string": "%}}",
            "variable_start_string": "{{{",
            "variable_end_string": "}}}",
            "comment_start_string": "{{#",
            "comment_end_string": "#}}",
        })

    jinja_env = SandboxedEnvironment(
        extensions=[B64EncodeExtension, RaiseErrorExtension],
        undefined=jinja2.StrictUndefined,
        **env,
    )
    jinja_env.filters.update({
        "json_to_dict": json_to_dict,
        "yaml_to_dict": yaml_to_dict,
        "urlescape": urlescape,
        "urlunescape": urlunescape,
        "eval": eval_filter,
        "extract_jsonpath": extract_jsonpath,
        "matches_jsonpath": matches_jsonpath,
        "json_pointers": json_pointers,
        "str_format": str_format,
    })

    return jinja_env.from_string(body)


GH_BASE_URL = os.environ.get("GITHUB_API", "https://api.github.com")


def init_github() -> Github:
    token = get_default_config()["token"]
    return Github(token, base_url=GH_BASE_URL)


def _get_or_create_lock(
    locks: dict[Any, threading.Lock],
    meta_lock: threading.Lock,
    key: Any,
) -> threading.Lock:
    with meta_lock:
        if key not in locks:
            locks[key] = threading.Lock()
        return locks[key]


_github_cache: dict[tuple[str, str, str], str] = {}
_github_locks: dict[tuple[str, str, str], threading.Lock] = {}
_github_locks_lock: threading.Lock = threading.Lock()


def _fetch_github_file_content(repo: str, path: str, ref: str) -> str:
    cache_key = (repo, path, ref)
    with _get_or_create_lock(_github_locks, _github_locks_lock, cache_key):
        if cache_key not in _github_cache:
            gh = init_github()
            content = GithubRepositoryApi.get_raw_file(
                repo=gh.get_repo(repo),
                path=path,
                ref=ref,
            )
            _github_cache[cache_key] = content.decode("utf-8")
    return _github_cache[cache_key]


def lookup_github_file_content(
    repo: str,
    path: str,
    ref: str,
    tvars: dict[str, Any] | None = None,
    settings: Mapping[str, Any] | None = None,
    secret_reader: SecretReaderBase | None = None,
) -> str:
    if tvars is not None:
        repo = process_jinja2_template(
            body=repo, vars=tvars, settings=settings, secret_reader=secret_reader
        )
        path = process_jinja2_template(
            body=path, vars=tvars, settings=settings, secret_reader=secret_reader
        )
        ref = process_jinja2_template(
            body=ref, vars=tvars, settings=settings, secret_reader=secret_reader
        )
    return _fetch_github_file_content(repo, path, ref)


_query_cache: dict[tuple[str, str], list[Any]] = {}
_query_locks: dict[tuple[str, str], threading.Lock] = {}
_query_locks_lock: threading.Lock = threading.Lock()


def lookup_graphql_query_results(query: str, **kwargs: dict[str, Any]) -> list[Any]:
    cache_key = (query, json.dumps(kwargs, sort_keys=True))
    with _get_or_create_lock(_query_locks, _query_locks_lock, cache_key):
        if cache_key not in _query_cache:
            gqlapi = gql.get_api()
            resource = gqlapi.get_resource(query)["content"]
            rendered_resource = jinja2.Template(resource).render(**kwargs)
            results = next(iter(gqlapi.query(rendered_resource).values()))
            _query_cache[cache_key] = results
    return _query_cache[cache_key]


_s3_cache: dict[tuple[str, str, str, str | None], str] = {}
_s3_locks: dict[tuple[str, str, str, str | None], threading.Lock] = {}
_s3_locks_lock: threading.Lock = threading.Lock()


def lookup_s3_object(
    account_name: str,
    bucket_name: str,
    path: str,
    region_name: str | None = None,
) -> str:
    cache_key = (account_name, bucket_name, path, region_name)
    with _get_or_create_lock(_s3_locks, _s3_locks_lock, cache_key):
        if cache_key not in _s3_cache:
            settings = queries.get_app_interface_settings()
            accounts = queries.get_aws_accounts(name=account_name)
            if not accounts:
                raise Exception(f"aws account not found: {account_name}")
            with AWSApi(1, accounts, settings=settings, init_users=False) as aws_api:
                _s3_cache[cache_key] = aws_api.get_s3_object_content(
                    account_name,
                    bucket_name,
                    path,
                    region_name=region_name,
                )
    return _s3_cache[cache_key]


_s3_ls_cache: dict[tuple[str, str, str, str | None], list[str]] = {}
_s3_ls_locks: dict[tuple[str, str, str, str | None], threading.Lock] = {}
_s3_ls_locks_lock: threading.Lock = threading.Lock()


def list_s3_objects(
    account_name: str,
    bucket_name: str,
    path: str,
    region_name: str | None = None,
) -> list[str]:
    cache_key = (account_name, bucket_name, path, region_name)
    with _get_or_create_lock(_s3_ls_locks, _s3_ls_locks_lock, cache_key):
        if cache_key not in _s3_ls_cache:
            settings = queries.get_app_interface_settings()
            accounts = queries.get_aws_accounts(name=account_name)
            if not accounts:
                raise Exception(f"aws account not found: {account_name}")
            with AWSApi(1, accounts, settings=settings, init_users=False) as aws_api:
                _s3_ls_cache[cache_key] = aws_api.list_s3_objects(
                    account_name,
                    bucket_name,
                    path,
                    region_name=region_name,
                )
    return _s3_ls_cache[cache_key]


# Caches all keys for a (path, version) in one read_all call.
# None sentinel means the path was not found; used to avoid re-fetching on cache hit.
# Keys within the same path are resolved locally without additional API calls.
_vault_path_cache: dict[tuple[str, str | None], dict[str, str] | None] = {}
_vault_path_locks: dict[tuple[str, str | None], threading.Lock] = {}
_vault_locks_lock: threading.Lock = threading.Lock()


@retry()
def _vault_read_all(
    secret_reader: SecretReaderBase,
    path: str,
    version: str | None,
) -> dict[str, str]:
    return secret_reader.read_all({"path": path, "field": "", "version": version})


def lookup_secret(
    path: str,
    key: str,
    version: str | None = None,
    tvars: dict[str, Any] | None = None,
    allow_not_found: bool = False,
    settings: Mapping[str, Any] | None = None,
    secret_reader: SecretReaderBase | None = None,
) -> str | None:
    if tvars is not None:
        path = process_jinja2_template(
            body=path, vars=tvars, settings=settings, secret_reader=secret_reader
        )
        key = process_jinja2_template(
            body=key, vars=tvars, settings=settings, secret_reader=secret_reader
        )
        if version and not isinstance(version, int):
            version = process_jinja2_template(
                body=version, vars=tvars, settings=settings, secret_reader=secret_reader
            )
    if not secret_reader:
        secret_reader = SecretReader(settings)
    # Normalize "LATEST" to None — both mean "current version" in Vault KV v2,
    # sharing a single cache entry avoids a redundant Vault read.
    if version is not None and str(version).upper() == "LATEST":
        version = None
    cache_key = (path, str(version) if version is not None else None)
    with _get_or_create_lock(_vault_path_locks, _vault_locks_lock, cache_key):
        if cache_key not in _vault_path_cache:
            try:
                fetched = _vault_read_all(secret_reader, path, version)
                _vault_path_cache[cache_key] = fetched
            except SecretNotFoundError:
                _vault_path_cache[cache_key] = None
            except Exception as e:
                raise FetchSecretError(e) from e
    secret_data = _vault_path_cache[cache_key]
    if secret_data is None:
        if allow_not_found:
            return None
        raise FetchSecretError(f"secret not found: {path}")
    if key not in secret_data:
        if allow_not_found:
            return None
        raise FetchSecretError(f"secret field not found: {path}/{key}")
    return secret_data[key]


def process_jinja2_template(
    body: str,
    vars: dict[str, Any] | None = None,
    extra_curly: bool = False,
    settings: Mapping[str, Any] | None = None,
    secret_reader: SecretReaderBase | None = None,
    template_render_options: TemplateRenderOptions | None = None,
) -> Any:
    if vars is None:
        vars = {}
    vars.update({
        "vault": lambda p, k, v=None, allow_not_found=False: lookup_secret(
            path=p,
            key=k,
            version=v,
            tvars=vars,
            allow_not_found=allow_not_found,
            settings=settings,
            secret_reader=secret_reader,
        ),
        "github": lambda u, p, r, v=None: lookup_github_file_content(
            repo=u,
            path=p,
            ref=r,
            tvars=vars,
            settings=settings,
            secret_reader=secret_reader,
        ),
        "urlescape": lambda u, s="/", e=None: urlescape(string=u, safe=s, encoding=e),
        "urlunescape": lambda u, e=None: urlunescape(string=u, encoding=e),
        "hash_list": hash_list,
        "query": lookup_graphql_query_results,
        "url": url_makes_sense,
        "s3": lookup_s3_object,
        "s3_ls": list_s3_objects,
        "flatten_dict": flatten,
        "yesterday": lambda: (utc_now() - datetime.timedelta(1)).strftime("%Y-%m-%d"),
        "sloth_alerts": generate_sloth_rules,
    })
    if "_template_mocks" in vars:
        for k, v in vars["_template_mocks"].items():
            vars[k] = lambda *args, **kwargs: v  # noqa: B023
    try:
        template = compile_jinja2_template(body, extra_curly, template_render_options)
        r = template.render(vars)
    except Exception as e:
        raise Jinja2TemplateError(e) from None
    return r


def process_extracurlyjinja2_template(
    body: str,
    vars: dict[str, Any] | None = None,
    extra_curly: bool = True,  # ignored. Just to be compatible with process_jinja2_template
    settings: Mapping[str, Any] | None = None,
    secret_reader: SecretReaderBase | None = None,
    template_render_options: TemplateRenderOptions | None = None,
) -> Any:
    if vars is None:
        vars = {}
    return process_jinja2_template(
        body,
        vars=vars,
        extra_curly=True,
        settings=settings,
        secret_reader=secret_reader,
        template_render_options=template_render_options,
    )


class FetchSecretError(Exception):
    def __init__(self, msg: Any):
        super().__init__("error fetching secret: " + str(msg))
