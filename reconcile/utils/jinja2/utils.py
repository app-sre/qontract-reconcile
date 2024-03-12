from functools import cache
from typing import Any, Optional

import jinja2
from jinja2.sandbox import SandboxedEnvironment
from sretoolbox.utils import retry

from reconcile import queries
from reconcile.checkpoint import url_makes_sense
from reconcile.github_users import init_github
from reconcile.utils import gql
from reconcile.utils.aws_api import AWSApi
from reconcile.utils.jinja2.extensions import B64EncodeExtension, RaiseErrorExtension
from reconcile.utils.jinja2.filters import (
    eval_filter,
    extract_jsonpath,
    hash_list,
    json_pointers,
    json_to_dict,
    matches_jsonpath,
    urlescape,
    urlunescape,
)
from reconcile.utils.secret_reader import SecretNotFound, SecretReader, SecretReaderBase


class Jinja2TemplateError(Exception):
    def __init__(self, msg: Any):
        super().__init__("error processing jinja2 template: " + str(msg))


@cache
def compile_jinja2_template(body: str, extra_curly: bool = False) -> Any:
    env: dict = {}
    if extra_curly:
        env = {
            "block_start_string": "{{%",
            "block_end_string": "%}}",
            "variable_start_string": "{{{",
            "variable_end_string": "}}}",
            "comment_start_string": "{{#",
            "comment_end_string": "#}}",
        }

    jinja_env = SandboxedEnvironment(
        extensions=[B64EncodeExtension, RaiseErrorExtension],
        undefined=jinja2.StrictUndefined,
        **env,
    )
    jinja_env.filters.update({
        "json_to_dict": json_to_dict,
        "urlescape": urlescape,
        "urlunescape": urlunescape,
        "eval": eval_filter,
        "extract_jsonpath": extract_jsonpath,
        "matches_jsonpath": matches_jsonpath,
        "json_pointers": json_pointers,
    })

    return jinja_env.from_string(body)


def lookup_github_file_content(
    repo: str,
    path: str,
    ref: str,
    tvars: Optional[dict[str, Any]] = None,
    settings: Optional[dict[str, Any]] = None,
    secret_reader: Optional[SecretReaderBase] = None,
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

    gh = init_github()
    c = gh.get_repo(repo).get_contents(path, ref).decoded_content
    return c.decode("utf-8")


def lookup_graphql_query_results(query: str, **kwargs: dict[str, Any]) -> list[Any]:
    gqlapi = gql.get_api()
    resource = gqlapi.get_resource(query)["content"]
    rendered_resource = jinja2.Template(resource).render(**kwargs)
    results = list(gqlapi.query(rendered_resource).values())[0]
    return results


def lookup_s3_object(
    account_name: str,
    bucket_name: str,
    path: str,
    region_name: Optional[str] = None,
) -> str:
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


@retry()
def lookup_secret(
    path: str,
    key: str,
    version: Optional[str] = None,
    tvars: Optional[dict[str, Any]] = None,
    allow_not_found: bool = False,
    settings: Optional[dict[str, Any]] = None,
    secret_reader: Optional[SecretReaderBase] = None,
) -> Optional[str]:
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
    secret = {"path": path, "field": key, "version": version}
    try:
        if not secret_reader:
            secret_reader = SecretReader(settings)
        return secret_reader.read(secret)
    except SecretNotFound as e:
        if allow_not_found:
            return None
        raise FetchSecretError(e)
    except Exception as e:
        raise FetchSecretError(e)


def process_jinja2_template(
    body: str,
    vars: Optional[dict[str, Any]] = None,
    extra_curly: bool = False,
    settings: Optional[dict[str, Any]] = None,
    secret_reader: Optional[SecretReaderBase] = None,
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
    })
    if "_template_mocks" in vars:
        for k, v in vars["_template_mocks"].items():
            vars[k] = lambda *args, **kwargs: v
    try:
        template = compile_jinja2_template(body, extra_curly)
        r = template.render(vars)
    except Exception as e:
        raise Jinja2TemplateError(e)
    return r


def process_extracurlyjinja2_template(
    body: str,
    vars: Optional[dict[str, Any]] = None,
    extra_curly: bool = True,
    settings: Optional[dict[str, Any]] = None,
    secret_reader: Optional[SecretReaderBase] = None,
) -> Any:
    if vars is None:
        vars = {}
    return process_jinja2_template(
        body,
        vars=vars,
        extra_curly=True,
        settings=settings,
        secret_reader=secret_reader,
    )


class FetchSecretError(Exception):
    def __init__(self, msg: Any):
        super().__init__("error fetching secret: " + str(msg))
