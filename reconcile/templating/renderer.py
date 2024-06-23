import json
import logging
import os
import tempfile
from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path
from typing import Any, Self

from ruamel import yaml

from reconcile.gql_definitions.templating.template_collection import (
    TemplateCollectionV1,
    TemplateCollectionVariablesV1,
    TemplateV1,
    query,
)
from reconcile.templating.lib.merge_request_manager import (
    MergeRequestManager,
    MrData,
    create_parser,
)
from reconcile.templating.lib.model import TemplateInput, TemplateOutput
from reconcile.templating.lib.rendering import (
    Renderer,
    TemplateData,
    create_renderer,
)
from reconcile.typed_queries.app_interface_repo_url import get_app_interface_repo_url
from reconcile.typed_queries.github_orgs import get_github_orgs
from reconcile.typed_queries.gitlab_instances import get_gitlab_instances
from reconcile.utils import gql
from reconcile.utils.git import clone
from reconcile.utils.gql import GqlApi, init_from_config
from reconcile.utils.jinja2.utils import TemplateRenderOptions, process_jinja2_template
from reconcile.utils.ruamel import create_ruamel_instance
from reconcile.utils.runtime.integration import (
    PydanticRunParams,
    QontractReconcileIntegration,
)
from reconcile.utils.secret_reader import SecretReaderBase
from reconcile.utils.vcs import VCS

QONTRACT_INTEGRATION = "template-renderer"

APP_INTERFACE_PATH_SEPERATOR = "/"


def get_template_collections(
    query_func: Callable | None = None, name: str | None = None
) -> list[TemplateCollectionV1]:
    variables = {}
    if name:
        variables["name"] = name
    if not query_func:
        query_func = gql.get_api().query
    return query(query_func, variables=variables).template_collection_v1 or []


class FilePersistence(ABC):
    @abstractmethod
    def write(self, outputs: list[TemplateOutput]) -> None:
        pass

    @abstractmethod
    def read(self, path: str) -> str | None:
        pass

    @staticmethod
    def _read_local_file(path: str) -> str | None:
        try:
            with open(
                path,
                encoding="utf-8",
            ) as f:
                return f.read()
        except FileNotFoundError:
            logging.debug(f"File not found: {path}, need to create it")
        return None


class LocalFilePersistence(FilePersistence):
    """
    This class provides a simple file persistence implementation for local files.
    """

    def __init__(self, app_interface_data_path: str) -> None:
        if not app_interface_data_path.endswith("/data"):
            raise ValueError("app_interface_data_path should end with /data")
        self.app_interface_data_path = app_interface_data_path

    def write(self, outputs: list[TemplateOutput]) -> None:
        for output in outputs:
            filepath = Path(join_path(self.app_interface_data_path, output.path))
            filepath.parent.mkdir(parents=True, exist_ok=True)
            filepath.write_text(output.content, encoding="utf-8")

    def read(self, path: str) -> str | None:
        return self._read_local_file(join_path(self.app_interface_data_path, path))


class PersistenceTransaction(FilePersistence):
    """
    This class provides a context manager to make read/write operations
    consistent. Reads/writes are beeing cached and writes are beeing delayed
    until the context is left.
    """

    def __init__(self, persistence: FilePersistence, dry_run: bool) -> None:
        self.persistence = persistence
        self.dry_run = dry_run
        self.content_cache: dict[str, str | None] = {}
        self.output_cache: dict[str, TemplateOutput] = {}

    def write(self, outputs: list[TemplateOutput]) -> None:
        for output in outputs:
            self.content_cache[output.path] = output.content
            self.output_cache[output.path] = output

    def read(self, path: str) -> str | None:
        if path not in self.content_cache:
            self.content_cache[path] = self.persistence.read(path)
        return self.content_cache[path]

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        if not self.dry_run and self.output_cache:
            self.persistence.write(list(self.output_cache.values()))


class ClonedRepoGitlabPersistence(FilePersistence):
    """
    This class is used to persist the rendered templates in a cloned gitlab repo
    Reads are from the local filesystem, writes are done via utils.VCS abstraction

    Only one MR is created per run. Auto-approval MRs are prefered.
    """

    def __init__(self, local_path: str, vcs: VCS, mr_manager: MergeRequestManager):
        self.local_path = join_path(local_path, "data")
        self.vcs = vcs
        self.mr_manager = mr_manager

    def write(self, outputs: list[TemplateOutput]) -> None:
        self.mr_manager.housekeeping()

        if any([o.input.enable_auto_approval for o in outputs]):
            auto_approved = [o for o in outputs if o.auto_approved]
            if auto_approved:
                self.mr_manager.create_merge_request(
                    MrData(data=auto_approved, auto_approved=True)
                )
                return

        self.mr_manager.create_merge_request(MrData(data=outputs, auto_approved=False))

    def read(self, path: str) -> str | None:
        return self._read_local_file(join_path(self.local_path, path))


def unpack_static_variables(
    collection_variables: TemplateCollectionVariablesV1,
    each: dict[str, Any],
) -> dict:
    return {
        k: json.loads(process_jinja2_template(body=json.dumps(v), vars={"each": each}))
        for k, v in (collection_variables.static or {}).items()
    }


def unpack_dynamic_variables(
    collection_variables: TemplateCollectionVariablesV1,
    each: dict[str, Any],
    gql: gql.GqlApi,
) -> dict[str, dict[str, Any]]:
    static = collection_variables.static or {}
    dynamic: dict[str, dict[str, Any]] = {}
    for dv in collection_variables.dynamic or []:
        query = process_jinja2_template(
            body=dv.query,
            vars={"static": static, "dynamic": dynamic, "each": each},
        )
        dynamic[dv.name] = gql.query(query) or {}
    return dynamic


class TemplateRendererIntegrationParams(PydanticRunParams):
    clone_repo: bool = False
    app_interface_data_path: str | None
    template_collection_name: str | None


def join_path(base: str, sub: str) -> str:
    return os.path.join(base, sub.lstrip(APP_INTERFACE_PATH_SEPERATOR))


class TemplateRendererIntegration(QontractReconcileIntegration):
    def __init__(self, params: TemplateRendererIntegrationParams) -> None:
        super().__init__(params)

    @staticmethod
    def _create_renderer(
        template: TemplateV1,
        variables: dict,
        secret_reader: SecretReaderBase | None = None,
    ) -> Renderer:
        return create_renderer(
            template,
            TemplateData(
                variables=variables,
            ),
            secret_reader=secret_reader,
            template_render_options=TemplateRenderOptions.create(
                trim_blocks=template.template_render_options.trim_blocks
                if template.template_render_options
                else None,
                lstrip_blocks=template.template_render_options.lstrip_blocks
                if template.template_render_options
                else None,
                keep_trailing_newline=template.template_render_options.keep_trailing_newline
                if template.template_render_options
                else None,
            ),
        )

    def process_template(
        self,
        template: TemplateV1,
        variables: dict,
        persistence: FilePersistence,
        ruaml_instance: yaml.YAML,
        template_input: TemplateInput,
    ) -> TemplateOutput | None:
        r = TemplateRendererIntegration._create_renderer(
            template, variables, secret_reader=self.secret_reader
        )
        target_path = r.render_target_path()

        current_str = persistence.read(
            target_path,
        )
        if current_str is None and template.patch:
            raise ValueError(f"Can not patch non-existing file {target_path}")

        if current_str:
            r.data.current = ruaml_instance.load(current_str)

        if r.render_condition():
            output = r.render_output()

            if current_str != output:
                logging.info(
                    f"diff for template {template.name} in target path {target_path}"
                )
                return TemplateOutput(
                    path=target_path,
                    content=output,
                    is_new=current_str is None,
                    auto_approved=template.auto_approved or False,
                    input=template_input,
                )
        return None

    def reconcile_template_collection(
        self,
        collection: TemplateCollectionV1,
        gql_api: GqlApi,
        persistence: FilePersistence,
        ruamel_instance: yaml.YAML,
        input: TemplateInput,
        each: dict[str, Any],
    ) -> list[TemplateOutput]:
        variables = {}
        if collection.variables:
            variables = {
                "dynamic": unpack_dynamic_variables(
                    collection.variables, each, gql_api
                ),
                "static": unpack_static_variables(collection.variables, each),
            }
            input.variables.append(variables)

        outputs: list[TemplateOutput] = []
        for template in collection.templates:
            output = self.process_template(
                template, variables, persistence, ruamel_instance, input
            )
            if output:
                outputs.append(output)

        return outputs

    def reconcile(
        self,
        dry_run: bool,
        persistence: FilePersistence,
        ruamel_instance: yaml.YAML,
    ) -> None:
        gql_no_validation = init_from_config(validate_schemas=False)
        for c in get_template_collections(name=self.params.template_collection_name):
            for_each_items: list[dict[str, Any]] = [{}]
            if c.for_each and c.for_each.items:
                for_each_items = c.for_each.items
            input = TemplateInput(
                collection=c.name,
                templates=c.templates,
                enable_auto_approval=c.enable_auto_approval or False,
                labels=c.additional_mr_labels or [],
            )
            with PersistenceTransaction(persistence, dry_run) as p:
                outputs: list[TemplateOutput] = []
                for item in for_each_items:
                    outputs.extend(
                        self.reconcile_template_collection(
                            c,
                            gql_no_validation,
                            p,
                            ruamel_instance,
                            input,
                            item,
                        )
                    )
                if not dry_run and outputs:
                    p.write(outputs)

    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    def run(self, dry_run: bool) -> None:
        persistence: FilePersistence
        ruaml_instance = create_ruamel_instance(explicit_start=True)

        if not self.params.clone_repo and self.params.app_interface_data_path:
            persistence = LocalFilePersistence(self.params.app_interface_data_path)
            self.reconcile(dry_run, persistence, ruaml_instance)

        elif self.params.clone_repo:
            gitlab_instances = get_gitlab_instances()
            vcs = VCS(
                secret_reader=self.secret_reader,
                github_orgs=get_github_orgs(),
                gitlab_instances=gitlab_instances,
                app_interface_repo_url=get_app_interface_repo_url(),
                dry_run=dry_run,
                allow_deleting_mrs=True,
                allow_opening_mrs=True,
            )
            merge_request_manager = MergeRequestManager(
                vcs=vcs,
                parser=create_parser(),
            )
            url = get_app_interface_repo_url()

            ssl_verify = next(
                g.ssl_verify for g in gitlab_instances if url.startswith(g.url)
            )

            with tempfile.TemporaryDirectory(
                prefix=f"{QONTRACT_INTEGRATION}-",
            ) as temp_dir:
                logging.debug(f"Cloning {url} to {temp_dir}")

                clone(url, temp_dir, depth=1, verify=ssl_verify)

                persistence = ClonedRepoGitlabPersistence(
                    temp_dir, vcs, merge_request_manager
                )

                self.reconcile(dry_run, persistence, ruaml_instance)

        else:
            raise ValueError("App-interface-data-path must be set")
