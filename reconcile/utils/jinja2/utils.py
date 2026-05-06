import datetime
import json
import os
import threading
from collections.abc import Callable, Mapping
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


_MISSING: Any = object()


class Jinja2TemplateCache:
    """Scoped cache for Jinja2 template external lookups (vault, github, s3, query).

    Create one instance per integration run and pass it to process_jinja2_template
    so all template renderings within a run share cached results. A fresh instance
    per run prevents stale data across loop iterations in run_integration.py.
    """

    GITHUB = "github"
    QUERY = "query"
    S3 = "s3"
    S3_LS = "s3_ls"
    VAULT = "vault"

    _NAMESPACES = (GITHUB, QUERY, S3, S3_LS, VAULT)

    def __init__(self) -> None:
        self._stores: dict[str, dict[Any, Any]] = {ns: {} for ns in self._NAMESPACES}
        self._locks: dict[str, dict[Any, threading.Lock]] = {
            ns: {} for ns in self._NAMESPACES
        }
        self._meta_locks: dict[str, threading.Lock] = {
            ns: threading.Lock() for ns in self._NAMESPACES
        }

    def _lock_for(self, namespace: str, key: Any) -> threading.Lock:
        meta = self._meta_locks[namespace]
        locks = self._locks[namespace]
        with meta:
            if key not in locks:
                locks[key] = threading.Lock()
            return locks[key]

    def get(self, namespace: str, key: Any) -> Any:
        return self._stores[namespace].get(key, _MISSING)

    def set(self, namespace: str, key: Any, value: Any) -> None:
        self._stores[namespace][key] = value

    def get_or_set(self, namespace: str, key: Any, compute: Callable[[], Any]) -> Any:
        with self._lock_for(namespace, key):
            if key not in self._stores[namespace]:
                self._stores[namespace][key] = compute()
        return self._stores[namespace][key]


def _fetch_github_file_content(
    repo: str, path: str, ref: str, cache: Jinja2TemplateCache
) -> str:
    def _fetch() -> str:
        gh = init_github()
        content = GithubRepositoryApi.get_raw_file(
            repo=gh.get_repo(repo),
            path=path,
            ref=ref,
        )
        return content.decode("utf-8")

    return cache.get_or_set(Jinja2TemplateCache.GITHUB, (repo, path, ref), _fetch)


def lookup_github_file_content(
    repo: str,
    path: str,
    ref: str,
    tvars: dict[str, Any] | None = None,
    settings: Mapping[str, Any] | None = None,
    secret_reader: SecretReaderBase | None = None,
    cache: Jinja2TemplateCache | None = None,
) -> str:
    cache = cache or Jinja2TemplateCache()
    if tvars is not None:
        repo = process_jinja2_template(
            body=repo,
            vars=tvars,
            settings=settings,
            secret_reader=secret_reader,
            cache=cache,
        )
        path = process_jinja2_template(
            body=path,
            vars=tvars,
            settings=settings,
            secret_reader=secret_reader,
            cache=cache,
        )
        ref = process_jinja2_template(
            body=ref,
            vars=tvars,
            settings=settings,
            secret_reader=secret_reader,
            cache=cache,
        )
    return _fetch_github_file_content(repo, path, ref, cache)


def lookup_graphql_query_results(
    query: str,
    cache: Jinja2TemplateCache | None = None,
    **kwargs: dict[str, Any],
) -> list[Any]:
    cache = cache or Jinja2TemplateCache()
    cache_key = (query, json.dumps(kwargs, sort_keys=True))

    def _fetch() -> list[Any]:
        gqlapi = gql.get_api()
        resource = gqlapi.get_resource(query)["content"]
        rendered_resource = jinja2.Template(resource).render(**kwargs)
        return next(iter(gqlapi.query(rendered_resource).values()))

    return cache.get_or_set(Jinja2TemplateCache.QUERY, cache_key, _fetch)


def lookup_s3_object(
    account_name: str,
    bucket_name: str,
    path: str,
    region_name: str | None = None,
    cache: Jinja2TemplateCache | None = None,
) -> str:
    cache = cache or Jinja2TemplateCache()
    cache_key = (account_name, bucket_name, path, region_name)

    def _fetch() -> str:
        settings = queries.get_app_interface_settings()
        accounts = queries.get_aws_accounts(name=account_name)
        if not accounts:
            raise Exception(f"aws account not found: {account_name}")
        with AWSApi(1, accounts, settings=settings, init_users=False) as aws_api:
            return aws_api.get_s3_object_content(
                account_name,
                bucket_name,
                path,
                region_name=region_name,
            )

    return cache.get_or_set(Jinja2TemplateCache.S3, cache_key, _fetch)


def list_s3_objects(
    account_name: str,
    bucket_name: str,
    path: str,
    region_name: str | None = None,
    cache: Jinja2TemplateCache | None = None,
) -> list[str]:
    cache = cache or Jinja2TemplateCache()
    cache_key = (account_name, bucket_name, path, region_name)

    def _fetch() -> list[str]:
        settings = queries.get_app_interface_settings()
        accounts = queries.get_aws_accounts(name=account_name)
        if not accounts:
            raise Exception(f"aws account not found: {account_name}")
        with AWSApi(1, accounts, settings=settings, init_users=False) as aws_api:
            return aws_api.list_s3_objects(
                account_name,
                bucket_name,
                path,
                region_name=region_name,
            )

    return cache.get_or_set(Jinja2TemplateCache.S3_LS, cache_key, _fetch)


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
    cache: Jinja2TemplateCache | None = None,
) -> str | None:
    cache = cache or Jinja2TemplateCache()
    if tvars is not None:
        path = process_jinja2_template(
            body=path,
            vars=tvars,
            settings=settings,
            secret_reader=secret_reader,
            cache=cache,
        )
        key = process_jinja2_template(
            body=key,
            vars=tvars,
            settings=settings,
            secret_reader=secret_reader,
            cache=cache,
        )
        if version and not isinstance(version, int):
            version = process_jinja2_template(
                body=version,
                vars=tvars,
                settings=settings,
                secret_reader=secret_reader,
                cache=cache,
            )
    if not secret_reader:
        secret_reader = SecretReader(settings)
    # Normalize "LATEST" to None — both mean "current version" in Vault KV v2,
    # sharing a single cache entry avoids a redundant Vault read.
    if version is not None and str(version).upper() == "LATEST":
        version = None
    cache_key = (path, str(version) if version is not None else None)

    sr = secret_reader

    def _fetch() -> dict[str, str] | None:
        try:
            return _vault_read_all(sr, path, version)
        except SecretNotFoundError:
            return None
        except Exception as e:
            raise FetchSecretError(e) from e

    secret_data = cache.get_or_set(Jinja2TemplateCache.VAULT, cache_key, _fetch)
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
    cache: Jinja2TemplateCache | None = None,
) -> Any:
    cache = cache or Jinja2TemplateCache()
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
            cache=cache,
        ),
        "github": lambda u, p, r, v=None: lookup_github_file_content(
            repo=u,
            path=p,
            ref=r,
            tvars=vars,
            settings=settings,
            secret_reader=secret_reader,
            cache=cache,
        ),
        "urlescape": lambda u, s="/", e=None: urlescape(string=u, safe=s, encoding=e),
        "urlunescape": lambda u, e=None: urlunescape(string=u, encoding=e),
        "hash_list": hash_list,
        "query": lambda q, **kw: lookup_graphql_query_results(q, cache=cache, **kw),
        "url": url_makes_sense,
        "s3": lambda a, b, p, r=None: lookup_s3_object(a, b, p, r, cache=cache),
        "s3_ls": lambda a, b, p, r=None: list_s3_objects(a, b, p, r, cache=cache),
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
    cache: Jinja2TemplateCache | None = None,
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
        cache=cache,
    )


class FetchSecretError(Exception):
    def __init__(self, msg: Any):
        super().__init__("error fetching secret: " + str(msg))
