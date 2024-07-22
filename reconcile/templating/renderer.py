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
from reconcile.templating.lib.model import TemplateOutput, TemplateResult
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
    def __init__(self, dry_run: bool) -> None:
        self.dry_run = dry_run
        self.outputs: list[TemplateOutput] = []
        self.result: TemplateResult | None = None

    def __enter__(self) -> Self:
        return self

    @abstractmethod
    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        pass

    def write(self, output: TemplateOutput) -> None:
        self.outputs.append(output)

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

    def __init__(self, dry_run: bool, app_interface_data_path: str) -> None:
        super().__init__(dry_run)
        if not app_interface_data_path.endswith("/data"):
            raise ValueError("app_interface_data_path should end with /data")
        self.app_interface_data_path = app_interface_data_path

    def read(self, path: str) -> str | None:
        return self._read_local_file(join_path(self.app_interface_data_path, path))

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        if self.dry_run:
            return
        for output in self.outputs:
            filepath = Path(join_path(self.app_interface_data_path, output.path))
            filepath.parent.mkdir(parents=True, exist_ok=True)
            filepath.write_text(output.content, encoding="utf-8")


class PersistenceTransaction(FilePersistence):
    """
    This class provides a context manager to make read/write operations
    consistent. Reads/writes are beeing cached and writes are being delayed
    until the context is left.
    """

    def __init__(self, persistence: FilePersistence) -> None:
        super().__init__(persistence.dry_run)
        self.persistence = persistence
        self.content_cache: dict[str, str | None] = {}
        self.output_cache: dict[str, TemplateOutput] = {}

    def write(self, output: TemplateOutput) -> None:
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
            for output in self.output_cache.values():
                self.persistence.write(output)


class ClonedRepoGitlabPersistence(FilePersistence):
    """
    This class is used to persist the rendered templates in a cloned gitlab repo
    Reads are from the local filesystem, writes are done via utils.VCS abstraction

    One MR is created per template-collection. Auto-approval MRs are prefered.
    """

    def __init__(
        self, dry_run: bool, local_path: str, vcs: VCS, mr_manager: MergeRequestManager
    ):
        super().__init__(dry_run)
        self.local_path = join_path(local_path, "data")
        self.vcs = vcs
        self.mr_manager = mr_manager

    def read(self, path: str) -> str | None:
        return self._read_local_file(join_path(self.local_path, path))

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        if self.result is None:
            raise ValueError("ClonedRepoGitlabPersistence.result not set!")
        self.result.outputs = self.outputs

        if self.dry_run or not self.outputs:
            return

        self.mr_manager.housekeeping()

        if self.result.enable_auto_approval:
            if auto_approved_outputs := [o for o in self.outputs if o.auto_approved]:
                # create an MR with auto-approved templates only
                self.mr_manager.create_merge_request(
                    MrData(
                        result=TemplateResult(
                            collection=f"{self.result.collection}-auto-approved",
                            enable_auto_approval=self.result.enable_auto_approval,
                            labels=self.result.labels,
                            outputs=auto_approved_outputs,
                        ),
                        auto_approved=True,
                    )
                )
            if not_auto_approved_outputs := [
                o for o in self.outputs if not o.auto_approved
            ]:
                # create an MR with not auto-approved templates only
                self.mr_manager.create_merge_request(
                    MrData(
                        result=TemplateResult(
                            collection=f"{self.result.collection}-not-auto-approved",
                            enable_auto_approval=self.result.enable_auto_approval,
                            labels=self.result.labels,
                            outputs=not_auto_approved_outputs,
                        ),
                        auto_approved=False,
                    )
                )
        else:
            # create an MR with all templates
            self.mr_manager.create_merge_request(
                MrData(result=self.result, auto_approved=False)
            )


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
    ) -> TemplateOutput | None:
        r = TemplateRendererIntegration._create_renderer(
            template, variables, secret_reader=self.secret_reader
        )
        target_path = r.render_target_path()
        current_file = persistence.read(target_path)
        if current_file is None and template.patch:
            raise ValueError(f"Can not patch non-existing file {target_path}")

        if current_file:
            r.data.current = ruaml_instance.load(current_file)

        if r.render_condition():
            output = r.render_output()

            if current_file != output:
                logging.info(
                    f"diff for template {template.name} in target path {target_path}"
                )
                return TemplateOutput(
                    path=target_path,
                    content=output,
                    is_new=current_file is None,
                    auto_approved=template.auto_approved or False,
                )
        return None

    def reconcile_template_collection(
        self,
        collection: TemplateCollectionV1,
        gql_api: GqlApi,
        persistence: FilePersistence,
        ruamel_instance: yaml.YAML,
        each: dict[str, Any],
    ) -> None:
        variables = {}
        if collection.variables:
            variables = {
                "dynamic": unpack_dynamic_variables(
                    collection.variables, each, gql_api
                ),
                "static": unpack_static_variables(collection.variables, each),
            }
        with PersistenceTransaction(persistence) as persistence_transaction:
            for template in collection.templates:
                if output := self.process_template(
                    template, variables, persistence_transaction, ruamel_instance
                ):
                    persistence_transaction.write(output)

    def reconcile(
        self, persistence: FilePersistence, ruamel_instance: yaml.YAML
    ) -> None:
        gql_api = init_from_config(validate_schemas=False)
        for collection in get_template_collections(
            name=self.params.template_collection_name
        ):
            for_each_items: list[dict[str, Any]] = [{}]
            if collection.for_each and collection.for_each.items:
                for_each_items = collection.for_each.items
            result = TemplateResult(
                collection=collection.name,
                enable_auto_approval=collection.enable_auto_approval or False,
                labels=collection.additional_mr_labels or [],
            )
            with persistence as p:
                p.result = result
                p.outputs = []
                for item in for_each_items:
                    self.reconcile_template_collection(
                        collection=collection,
                        gql_api=gql_api,
                        persistence=p,
                        ruamel_instance=ruamel_instance,
                        each=item,
                    )

    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    def run(self, dry_run: bool) -> None:
        persistence: FilePersistence
        ruaml_instance = create_ruamel_instance(explicit_start=True)

        if not self.params.clone_repo and self.params.app_interface_data_path:
            persistence = LocalFilePersistence(
                dry_run=dry_run,
                app_interface_data_path=self.params.app_interface_data_path,
            )
            self.reconcile(persistence, ruaml_instance)

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
                    dry_run=dry_run,
                    local_path=temp_dir,
                    vcs=vcs,
                    mr_manager=merge_request_manager,
                )
                self.reconcile(persistence, ruaml_instance)

        else:
            raise ValueError("App-interface-data-path must be set")
