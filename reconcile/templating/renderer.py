import logging
import os
import tempfile
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any, Optional, Self

from deepdiff import DeepHash
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
    TemplateData,
    create_renderer,
)
from reconcile.typed_queries.app_interface_repo_url import get_app_interface_repo_url
from reconcile.typed_queries.github_orgs import get_github_orgs
from reconcile.typed_queries.gitlab_instances import get_gitlab_instances
from reconcile.utils import gql
from reconcile.utils.git import clone
from reconcile.utils.gql import init_from_config
from reconcile.utils.ruamel import create_ruamel_instance
from reconcile.utils.runtime.integration import (
    PydanticRunParams,
    QontractReconcileIntegration,
)
from reconcile.utils.vcs import VCS

QONTRACT_INTEGRATION = "template-renderer"

APP_INTERFACE_PATH_SEPERATOR = "/"


def get_template_collections(
    query_func: Optional[Callable] = None,
) -> list[TemplateCollectionV1]:
    if not query_func:
        query_func = gql.get_api().query
    return query(query_func).template_collection_v1 or []


class FilePersistence(ABC):
    @abstractmethod
    def write(self, outputs: list[TemplateOutput]) -> None:
        pass

    @abstractmethod
    def read(self, path: str) -> Optional[str]:
        pass

    @staticmethod
    def _read_local_file(path: str) -> Optional[str]:
        try:
            with open(
                path,
                "r",
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
            with open(
                f"{join_path(self.app_interface_data_path, output.path)}",
                "w",
                encoding="utf-8",
            ) as f:
                f.write(output.content)

    def read(self, path: str) -> Optional[str]:
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
        self.content_cache: dict[str, Optional[str]] = {}
        self.output_cache: dict[str, TemplateOutput] = {}

    def write(self, outputs: list[TemplateOutput]) -> None:
        for output in outputs:
            self.content_cache[output.path] = output.content
            self.output_cache[output.path] = output

    def read(self, path: str) -> Optional[str]:
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

    def read(self, path: str) -> Optional[str]:
        return self._read_local_file(join_path(self.local_path, path))


def unpack_static_variables(
    collection_variables: TemplateCollectionVariablesV1,
) -> dict:
    return collection_variables.static or {}


def unpack_dynamic_variables(
    collection_variables: TemplateCollectionVariablesV1, gql: gql.GqlApi
) -> dict[str, dict[str, Any]]:
    if not collection_variables.dynamic:
        return {}

    return {
        dv.name: gql.query(dv.query) or {} for dv in collection_variables.dynamic or []
    }


def calc_template_hash(c: TemplateCollectionV1, variables: dict[str, Any]) -> str:
    hashable = {
        "templates": sorted(c.templates, key=lambda x: x.name),
        "variables": variables,
    }
    return DeepHash(hashable)[hashable]


class TemplateRendererIntegrationParams(PydanticRunParams):
    clone_repo: bool = False
    app_interface_data_path: Optional[str]


def join_path(base: str, sub: str) -> str:
    return os.path.join(base, sub.lstrip(APP_INTERFACE_PATH_SEPERATOR))


class TemplateRendererIntegration(QontractReconcileIntegration):
    def __init__(self, params: TemplateRendererIntegrationParams) -> None:
        super().__init__(params)

    def process_template(
        self,
        template: TemplateV1,
        variables: dict,
        persistence: FilePersistence,
        ruaml_instance: yaml.YAML,
        template_input: TemplateInput,
    ) -> Optional[TemplateOutput]:
        r = create_renderer(
            template,
            TemplateData(
                variables=variables,
            ),
            secret_reader=self.secret_reader,
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

    def reconcile(
        self,
        dry_run: bool,
        persistence: FilePersistence,
        ruamel_instance: yaml.YAML,
    ) -> None:
        gql_no_validation = init_from_config(validate_schemas=False)

        for c in get_template_collections():
            variables = {}
            if c.variables:
                variables = {
                    "dynamic": unpack_dynamic_variables(c.variables, gql_no_validation),
                    "static": unpack_static_variables(c.variables),
                }

            with PersistenceTransaction(persistence, dry_run) as p:
                input = TemplateInput(
                    collection=c.name,
                    collection_hash=calc_template_hash(c, variables),
                    enable_auto_approval=c.enable_auto_approval or False,
                    labels=c.additional_mr_labels or [],
                )
                for template in c.templates:
                    output = self.process_template(
                        template, variables, p, ruamel_instance, input
                    )
                    if not dry_run and output:
                        p.write([output])

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
