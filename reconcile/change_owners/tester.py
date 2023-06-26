import os
import sys
from collections.abc import Generator
from dataclasses import dataclass
from typing import (
    Any,
    Optional,
)

import jsonpath_ng
import pygments
import pygments.lexers
import yaml
from pygments.filter import Filter
from pygments.formatters.terminal256 import TerminalTrueColorFormatter
from pygments.token import Name

from reconcile.change_owners.change_owners import fetch_change_type_processors
from reconcile.change_owners.change_types import (
    BundleFileType,
    ChangeTypeProcessor,
    FileRef,
)
from reconcile.change_owners.changes import (
    BundleFileChange,
    parse_resource_file_content,
)
from reconcile.change_owners.self_service_roles import (
    change_type_contexts_for_self_service_roles,
)
from reconcile.gql_definitions.change_owners.queries import self_service_roles
from reconcile.gql_definitions.change_owners.queries.self_service_roles import RoleV1
from reconcile.utils import gql


def test_change_type_in_context(
    change_type_name: str, role_name: str, app_interface_path: str
) -> None:
    print(f"Sections marked with '{SELF_SERVICABLE_MARKER}' are self serviceable\n\n")

    role = get_self_service_role_by_name(role_name)
    if role is None:
        print(f"Role {role_name} not found")
        sys.exit(1)

    app_interface_path = os.path.expanduser(app_interface_path)
    if not os.path.isdir(app_interface_path):
        print(f"app-interface directory {app_interface_path} not found")
        sys.exit(1)
    if not os.path.isfile(f"{app_interface_path}/.env"):
        print(
            f"app-interface directory {app_interface_path} does not contain a .env file. "
            "maybe not an app-interface dir?"
        )
        sys.exit(1)
    ai_repo = AppInterfaceRepo(app_interface_path)

    change_type_processor = get_changetype_processor_by_name(change_type_name, ai_repo)
    if change_type_processor is None:
        print(f"Change type {change_type_name} not found")
        sys.exit(1)

    bundle_files = ai_repo.relevant_bundle_files_for_change_type(
        role, change_type_processor
    )

    change_type_contexts = change_type_contexts_for_self_service_roles(
        roles=[role],
        change_type_processors=[change_type_processor],
        bundle_changes=bundle_files,
    )

    for file, ctx in change_type_contexts:
        self_serviceable_paths = change_type_processor.allowed_changed_paths(
            file_ref=file.fileref, file_content=file.new, ctx=ctx
        )
        if self_serviceable_paths:
            print_annotated_file(file, self_serviceable_paths)


SELF_SERVICABLE_MARKER = "self-serviceable"


def print_annotated_file(
    file: BundleFileChange, self_serviceable_paths: list[jsonpath_ng.JSONPath]
) -> None:
    # add a markers to the data to indicate which parts are self serviceable
    for path_expression in self_serviceable_paths:
        for self_serviceable_data in path_expression.find(file.new):
            self_serviceable_data.full_path.update(
                file.new, {SELF_SERVICABLE_MARKER: self_serviceable_data.value}
            )

    print(f"File - {file.fileref.path}\n")
    lexer = pygments.lexers.YamlLexer()
    lexer.add_filter(SelfServiceableHighlighter(SELF_SERVICABLE_MARKER))
    pygments.highlight(
        yaml.dump(file.new, sort_keys=False),
        lexer,
        TerminalTrueColorFormatter(),
        sys.stdout,
    )
    print("\n=======================================\n\n")


@dataclass
class AppInterfaceRepo:
    root_dir: str

    def data_dir(self) -> str:
        return f"{self.root_dir}/data"

    def resource_dir(self) -> str:
        return f"{self.root_dir}/resources"

    def relevant_bundle_files_for_change_type(
        self,
        role: RoleV1,
        ctp: ChangeTypeProcessor,
    ) -> list[BundleFileChange]:
        bundle_files = []
        processed_schemas = set()
        for c in ctp.change_detectors:
            if (
                c.change_schema
                and c.change_schema != ctp.context_schema
                and c.change_schema not in processed_schemas
            ):
                # the changes can happen in other files, not the one related
                # under RoleV1.self_service
                bundle_files.extend(self.bundle_files_with_schemas(c.change_schema))
                processed_schemas.add(c.change_schema)
            elif c.change_schema is None or c.change_schema == ctp.context_schema:
                # the change happens in the self_service related files
                for ssc in role.self_service or []:
                    for df in ssc.datafiles or []:
                        bundle_files.append(
                            self.bundle_file_for_path(BundleFileType.DATAFILE, df.path)
                        )
                    for rf_path in ssc.resources or []:
                        bundle_files.append(
                            self.bundle_file_for_path(
                                BundleFileType.RESOURCEFILE, rf_path
                            )
                        )
        return bundle_files

    def bundle_files_with_schemas(self, schema: str) -> list[BundleFileChange]:
        datafiles = []
        for root, _, files in os.walk(self.data_dir()):
            for file in files:
                if file.endswith(".yml") or file.endswith(".yaml"):
                    filepath = os.path.join(root, file)
                    with open(filepath, "r") as f:
                        parsed_yaml = yaml.safe_load(f)
                        if parsed_yaml.get("$schema") == schema:
                            relative_path = filepath[len(self.data_dir()) :]
                            datafiles.append(
                                self.bundle_file_for_path(
                                    BundleFileType.DATAFILE, relative_path
                                )
                            )
        return datafiles

    def bundle_file_for_path(
        self, file_type: BundleFileType, path: str
    ) -> BundleFileChange:
        if file_type == BundleFileType.DATAFILE:
            with open(f"{self.data_dir()}{path}", "r") as f:
                parsed_yaml = yaml.safe_load(f)
                return BundleFileChange(
                    fileref=FileRef(
                        path=path,
                        file_type=file_type,
                        schema=parsed_yaml.get("$schema"),
                    ),
                    old=parsed_yaml,
                    new=parsed_yaml,
                    old_content_sha="",
                    new_content_sha="",
                    diffs=[],
                )
        elif file_type == BundleFileType.RESOURCEFILE:
            with open(f"{self.resource_dir()}{path}", "r") as f:
                content = f.read()
                parsed_content, schema = parse_resource_file_content(content)
                return BundleFileChange(
                    fileref=FileRef(
                        path=path,
                        file_type=file_type,
                        schema=schema,
                    ),
                    old=parsed_content,
                    new=parsed_content,
                    old_content_sha="",
                    new_content_sha="",
                    diffs=[],
                )
        else:
            raise ValueError(f"Unknown file type {file_type}")


class SelfServiceableHighlighter(Filter):
    """
    This pygments filter is used to highlight the self service marker
    in a structured file.
    """

    def __init__(self, self_serviceable_marker: str) -> None:
        Filter.__init__(self)
        self.self_serviceable_marker = self_serviceable_marker

    def filter(self, _: Any, stream: Any) -> Generator[tuple[Any, Any], None, None]:
        for ttype, value in stream:
            if value != self.self_serviceable_marker:
                ttype = Name
            yield ttype, value


class FilesystemFileDiffResolver:
    def __init__(self, app_interface_repo: AppInterfaceRepo) -> None:
        self.app_interface_repo = app_interface_repo

    def lookup_file_diff(
        self, file_ref: FileRef
    ) -> tuple[Optional[dict[str, Any]], Optional[dict[str, Any]]]:
        file = self.app_interface_repo.bundle_file_for_path(
            file_type=file_ref.file_type, path=file_ref.path
        )
        return file.old, file.new


def get_changetype_processor_by_name(
    change_type_name: str, app_interface_repo: AppInterfaceRepo
) -> Optional[ChangeTypeProcessor]:
    processors = fetch_change_type_processors(
        gql.get_api(), FilesystemFileDiffResolver(app_interface_repo)
    )
    return next((p for p in processors if p.name == change_type_name), None)


def get_self_service_role_by_name(
    role_name: str,
) -> Optional[RoleV1]:
    result = self_service_roles.query(
        gql.get_api().query, variables={"name": role_name}
    ).roles
    if result:
        return result[0]
    return None
