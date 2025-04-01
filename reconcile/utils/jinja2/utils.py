import datetime
from functools import cache
from typing import Any, Self

import jinja2
from jinja2.sandbox import SandboxedEnvironment
from pydantic import BaseModel
from sretoolbox.utils import retry

from reconcile import queries
from reconcile.checkpoint import url_makes_sense
from reconcile.github_users import init_github
from reconcile.utils import gql
from reconcile.utils.aws_api import AWSApi
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
from reconcile.utils.secret_reader import SecretNotFound, SecretReader, SecretReaderBase
from reconcile.utils.vault import SecretFieldNotFound


class Jinja2TemplateError(Exception):
    def __init__(self, msg: Any):
        super().__init__("error processing jinja2 template: " + str(msg))


class TemplateRenderOptions(BaseModel):
    trim_blocks: bool
    lstrip_blocks: bool
    keep_trailing_newline: bool

    class Config:
        frozen = True

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
    env: dict[str, Any] = template_render_options.dict()
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


def lookup_github_file_content(
    repo: str,
    path: str,
    ref: str,
    tvars: dict[str, Any] | None = None,
    settings: dict[str, Any] | None = None,
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

    gh = init_github()
    content = gh.get_repo(repo).get_contents(path, ref)
    if isinstance(content, list):
        raise Exception(f"multiple files found for {repo}/{path}/{ref}")
    return content.decoded_content.decode("utf-8")


def lookup_graphql_query_results(query: str, **kwargs: dict[str, Any]) -> list[Any]:
    gqlapi = gql.get_api()
    resource = gqlapi.get_resource(query)["content"]
    rendered_resource = jinja2.Template(resource).render(**kwargs)
    results = next(iter(gqlapi.query(rendered_resource).values()))
    return results


def lookup_s3_object(
    account_name: str,
    bucket_name: str,
    path: str,
    region_name: str | None = None,
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


def list_s3_objects(
    account_name: str,
    bucket_name: str,
    path: str,
    region_name: str | None = None,
) -> list[str]:
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


@retry()
def lookup_secret(
    path: str,
    key: str,
    version: str | None = None,
    tvars: dict[str, Any] | None = None,
    allow_not_found: bool = False,
    settings: dict[str, Any] | None = None,
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
    secret = {"path": path, "field": key, "version": version}
    try:
        if not secret_reader:
            secret_reader = SecretReader(settings)
        return secret_reader.read(secret)
    except (SecretNotFound, SecretFieldNotFound) as e:
        if allow_not_found:
            return None
        raise FetchSecretError(e) from None
    except Exception as e:
        raise FetchSecretError(e) from e


def process_jinja2_template(
    body: str,
    vars: dict[str, Any] | None = None,
    extra_curly: bool = False,
    settings: dict[str, Any] | None = None,
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
        "yesterday": lambda: (datetime.datetime.now() - datetime.timedelta(1)).strftime(
            "%Y-%m-%d"
        ),
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
    settings: dict[str, Any] | None = None,
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
