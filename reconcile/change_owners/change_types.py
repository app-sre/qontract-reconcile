from dataclasses import dataclass
from collections import defaultdict
from enum import Enum
from typing import Any, Iterable, Optional, Sequence, Tuple


import jsonpath_ng
import jsonpath_ng.ext
import anymarkup
import jinja2
import jinja2.meta
import networkx

from reconcile.change_owners.diff import (
    SHA256SUM_FIELD_NAME,
    Diff,
    DiffType,
    extract_diffs,
)
from reconcile.gql_definitions.change_owners.queries.change_types import (
    ChangeTypeV1,
    ChangeTypeChangeDetectorJsonPathProviderV1,
    ChangeTypeChangeDetectorV1,
)


class BundleFileType(Enum):
    DATAFILE = "datafile"
    RESOURCEFILE = "resourcefile"


@dataclass(frozen=True)
class FileRef:
    file_type: BundleFileType
    path: str
    schema: Optional[str]


@dataclass
class DiffCoverage:
    diff: Diff
    coverage: list["ChangeTypeContext"]

    def is_covered(self) -> bool:
        """
        a diff is considered covered, if there is at least one change-type
        assosciated that is not disabled
        """
        return any(not ctx.disabled for ctx in self.coverage)


@dataclass
class BundleFileChange:
    """
    Represents a file within an app-interface bundle that changed during an MR.
    It holds the old and new state of that file, along with precise differences
    between those states.
    """

    fileref: FileRef
    old: Optional[dict[str, Any]]
    new: Optional[dict[str, Any]]
    diff_coverage: list[DiffCoverage]

    def extract_context_file_refs(
        self, change_type: "ChangeTypeProcessor"
    ) -> list[FileRef]:
        """
        ChangeTypeV1 are attached to bundle files, react to changes within
        them and use their context to derive who can approve those changes.
        Extracting this context can be done in two ways depending on the configuration
        of the ChangeTypeV1.

        direct context extraction
          If a ChangeTypeV1 defines a `context_schema`, it can be attached to files
          of that schema. If such a file changes, the ChangeTypeV1 feels responsible
          for it in subsequent diff coverage calculations and will use the approvers
          that exist in the context of that changed file. This is the default
          mode almost all ChangeTypeV1 operate in.

          Example: a ChangeTypeV1 defines `/openshift/namespace-1.yml` as the
          context_schema and can cover certain changes in it. If this ChangeTypeV1
          is attached to certain namespace files (potential BundleChanges) and
          a Role (context), changes in those namespace files can be approved by
          members of the role.

        context detection
          If a ChangeTypeV1 additionally defines change_schemas and context selectors,
          it has the capability to differentiate between reacting to changes
          (and trying to cover them) and finding the context where approvers are
          defined.

          Example: Consider the following ChangeTypeV1 granting permissions to
          approve on new members wanting to join a role.
          ```
            $schema: /app-interface/change-type-1.yml

            contextType: datafile
            contextSchema: /access/roles-1.yml

            changes:
            - provider: jsonPath
              changeSchema: /access/user-1.yml
              jsonPathSelectors:
              - roles[*]
              context:
                selector: roles[*].'$ref'
                when: added
          ```

          Users join a role by adding the role to the user. This means that it
          is a /access/user-1.yml file that changes in this situation. But permissions
          to approve changes should be attached to the role not the user. This
          ChangeTypeV1 takes care of that differentiation by defining /access/role-1.yml
          as the context schema (making the ChangeTypeV1 assignable to a role)
          but defining change detection on /access/user-1.yml via the `changeSchema`.
          The actual role can be found within the userfile by looking for `added`
          entries under `roles[*].$ref` (this is a jsonpath expression) as defined
          under `context.selector`.
        """
        if not change_type.changes:
            return []

        # direct context extraction
        # the changed file itself is giving the context for approver extraction
        # see doc string for more details
        if change_type.context_schema == self.fileref.schema:
            return [self.fileref]

        # context detection
        # the context for approver extraction can be found within the changed
        # file with a `context.selector`
        # see doc string for more details
        contexts: list[FileRef] = []
        for c in change_type.changes:
            if c.change_schema == self.fileref.schema and c.context:
                context_selector = jsonpath_ng.ext.parse(c.context.selector)
                old_contexts = {e.value for e in context_selector.find(self.old)}
                new_contexts = {e.value for e in context_selector.find(self.new)}
                if c.context.when == "added":
                    affected_context_paths = new_contexts - old_contexts
                elif c.context.when == "removed":
                    affected_context_paths = old_contexts - new_contexts
                elif c.context.when is None and old_contexts == new_contexts:
                    affected_context_paths = old_contexts
                else:
                    affected_context_paths = None

                if affected_context_paths:
                    contexts.extend(
                        [
                            FileRef(
                                schema=change_type.context_schema,
                                path=path,
                                file_type=BundleFileType.DATAFILE,
                            )
                            for path in affected_context_paths
                        ]
                    )
        return contexts

    def cover_changes(self, change_type_context: "ChangeTypeContext") -> list[Diff]:
        """
        Figure out if a ChangeTypeV1 covers detected changes within the BundleFile.
        Base idea:

        - a ChangeTypeV1 defines path patterns that are considered self-approvable
        - if a change (diff) is located under one of the allowed paths of the
          ChangeTypeV1, it is considered "covered" by that ChangeTypeV1 in a certain
          context (e.g. a RoleV1) and allows the approvers of that context (e.g.
          the members of that role) to approve that particular change.

        The change-type contexts that cover a change, are registered in the
        `DiffCoverage.coverage` list right next to the Diff that is covered.
        """
        covered_diffs = {}
        # observe the new state for added fields or list items or entire object sutrees
        covered_diffs.update(
            self._cover_changes_for_diffs(
                self._filter_diffs([DiffType.ADDED, DiffType.CHANGED]),
                self.new,
                change_type_context,
            )
        )
        # look at the old state for removed fields or list items or object subtrees
        covered_diffs.update(
            self._cover_changes_for_diffs(
                self._filter_diffs([DiffType.REMOVED]), self.old, change_type_context
            )
        )
        return list(covered_diffs.values())

    def _cover_changes_for_diffs(
        self,
        diffs: list[DiffCoverage],
        file_content: Any,
        change_type_context: "ChangeTypeContext",
    ) -> dict[str, Diff]:

        covered_diffs = {}
        if diffs:
            for (
                allowed_path
            ) in change_type_context.change_type_processor.allowed_changed_paths(
                self.fileref, file_content, change_type_context
            ):
                for dc in diffs:
                    if change_path_covered_by_allowed_path(
                        str(dc.diff.path), allowed_path
                    ):
                        covered_diffs[str(dc.diff.path)] = dc.diff
                        dc.coverage.append(change_type_context)
        return covered_diffs

    def _filter_diffs(self, diff_types: list[DiffType]) -> list[DiffCoverage]:
        return [d for d in self.diff_coverage if d.diff.diff_type in diff_types]

    def uncovered_changes(self) -> Iterable[DiffCoverage]:
        return (d for d in self.diff_coverage if not d.is_covered())

    def all_changes_covered(self) -> bool:
        return not any(self.uncovered_changes())


def parse_resource_file_content(content: Optional[Any]) -> Tuple[Any, Optional[str]]:
    if content:
        try:
            data = anymarkup.parse(content, force_types=None)
            return data, data.get("$schema")
        except Exception:
            # not parsable content - we will just deal with the plain content
            return content, None
    else:
        return None, None


def create_bundle_file_change(
    path: str,
    schema: Optional[str],
    file_type: BundleFileType,
    old_file_content: Any,
    new_file_content: Any,
) -> Optional[BundleFileChange]:
    """
    this is a factory method that creates a BundleFileChange object based
    on the old and new content of a file from app-interface. it detects differences
    within the old and new state of the file and represents them as instances
    of the Diff dataclass. for diff detection, the amazing `deepdiff` python
    library is used.
    """
    fileref = FileRef(path=path, schema=schema, file_type=file_type)

    # try to parse the content of a resourcefile
    # it falls back to the plain file content if parsing does not work
    if file_type == BundleFileType.RESOURCEFILE:
        old_file_content, _ = parse_resource_file_content(old_file_content)
        new_file_content, _ = parse_resource_file_content(new_file_content)

    diffs = extract_diffs(
        old_file_content=old_file_content,
        new_file_content=new_file_content,
    )

    if diffs:
        return BundleFileChange(
            fileref=fileref,
            old=old_file_content,
            new=new_file_content,
            diff_coverage=[DiffCoverage(d, []) for d in diffs],
        )
    else:
        return None


class PathExpression:
    """
    PathExpression is a wrapper around a JSONPath expression that can contain
    Jinja2 template fragments. The template has access to ChangeTypeContext.
    """

    CTX_FILE_PATH_VAR_NAME = "ctx_file_path"
    SUPPORTED_VARS = {CTX_FILE_PATH_VAR_NAME}

    def __init__(self, jsonpath_expression: str):
        self.jsonpath_expression = jsonpath_expression
        self.parsed_jsonpath = None
        if "{{" in jsonpath_expression:
            env = jinja2.Environment()
            ast = env.parse(self.jsonpath_expression)
            used_variable = jinja2.meta.find_undeclared_variables(ast)
            if used_variable - self.SUPPORTED_VARS:
                raise ValueError(
                    f"only the variables '{self.SUPPORTED_VARS}' are allowed "
                    f"in path expressions. found: {used_variable}"
                )
            self.template = env.from_string(self.jsonpath_expression)
        else:
            self.parsed_jsonpath = jsonpath_ng.ext.parse(jsonpath_expression)

    def jsonpath_for_context(self, ctx: "ChangeTypeContext") -> jsonpath_ng.JSONPath:
        if self.parsed_jsonpath:
            return self.parsed_jsonpath
        else:
            expr = self.template.render(
                {
                    self.CTX_FILE_PATH_VAR_NAME: ctx.context_file.path,
                }
            )
            return jsonpath_ng.ext.parse(expr)


@dataclass
class ChangeTypeProcessor:
    """
    ChangeTypeProcessor wraps the generated GQL class ChangeTypeV1 and adds
    functionality that operates close on the configuration of the ChangeTypeV1,
    like computing the jsonpaths that are allowed to change in a file.
    """

    name: str
    context_type: BundleFileType
    context_schema: Optional[str]
    disabled: bool

    def __post_init__(self):
        self._expressions_by_file_type_schema: dict[
            Tuple[BundleFileType, Optional[str]], list[PathExpression]
        ] = defaultdict(list)
        self._changes: list[ChangeTypeChangeDetectorV1] = []

    @property
    def changes(self) -> Sequence[ChangeTypeChangeDetectorV1]:
        return self._changes

    def allowed_changed_paths(
        self, file_ref: FileRef, file_content: Any, ctx: "ChangeTypeContext"
    ) -> list[str]:
        """
        find all paths within the provide file_content, that are covered by this
        ChangeTypeV1. the paths are represented as jsonpath expressions pinpointing
        the root element that can be changed
        """
        paths = []
        if (
            file_ref.file_type,
            file_ref.schema,
        ) in self._expressions_by_file_type_schema:
            for change_type_path_expression in self._expressions_by_file_type_schema[
                (file_ref.file_type, file_ref.schema)
            ]:
                paths.extend(
                    [
                        str(p.full_path)
                        for p in change_type_path_expression.jsonpath_for_context(
                            ctx
                        ).find(file_content)
                    ]
                )
        return paths

    def add_change(self, change: ChangeTypeChangeDetectorV1) -> None:
        self._changes.append(change)
        if isinstance(change, ChangeTypeChangeDetectorJsonPathProviderV1):
            change_schema = change.change_schema or self.context_schema
            for jsonpath_expression in change.json_path_selectors + [
                f"'{SHA256SUM_FIELD_NAME}'"
            ]:
                self._expressions_by_file_type_schema[
                    (self.context_type, change_schema)
                ].append(PathExpression(jsonpath_expression))
        else:
            raise ValueError(
                f"{change.provider} is not a supported change detection provider within ChangeTypes"
            )


def build_change_type_processor(change_type: ChangeTypeV1) -> ChangeTypeProcessor:
    """
    Build a ChangeTypeProcessor from a ChangeTypeV1 and pre-initializing jsonpaths.
    """
    ctp = ChangeTypeProcessor(
        name=change_type.name,
        context_type=BundleFileType[change_type.context_type.upper()],
        context_schema=change_type.context_schema,
        disabled=bool(change_type.disabled),
    )
    for change in change_type.changes:
        ctp.add_change(change)
    return ctp


def init_change_type_processors(
    change_types: Sequence[ChangeTypeV1],
) -> dict[str, ChangeTypeProcessor]:
    processors = {}
    change_type_graph = networkx.DiGraph()
    for change_type in change_types:
        change_type_graph.add_node(change_type.name)
        for i in change_type.inherit or []:
            change_type_graph.add_edge(change_type.name, i.name)
        processors[change_type.name] = build_change_type_processor(change_type)

    # detect cycles
    if cycles := list(networkx.simple_cycles(change_type_graph)):
        raise ChangeTypeInheritanceCycleError(
            "Cycles detected in change-type inheritance", cycles
        )

    # aggregate inherited changes
    for ctp in processors.values():
        for d in networkx.descendants(change_type_graph, ctp.name):
            if ctp.context_type != processors[d].context_type:
                raise ChangeTypeIncompatibleInheritanceError(
                    f"change-type '{ctp.name}' inherits from '{d}' "
                    "but has a different context_type"
                )
            if ctp.context_schema != processors[d].context_schema:
                raise ChangeTypeIncompatibleInheritanceError(
                    f"change-type '{ctp.name}' inherits from '{d}' "
                    "but has a different context_schema"
                )
            for change in processors[d].changes:
                ctp.add_change(change)

    return processors


class ChangeTypeIncompatibleInheritanceError(ValueError):
    pass


class ChangeTypeInheritanceCycleError(ValueError):
    pass


@dataclass
class Approver:
    """
    Minimalistic wrapper for approver sources to be used in ChangeTypeContexts.
    Since we might load different approver contexts via GraphQL query classes,
    a wrapper enables us to deal with different dataclasses representing an
    approver.
    """

    org_username: str
    tag_on_merge_requests: Optional[bool] = False


@dataclass
class ChangeTypeContext:
    """
    A ChangeTypeContext represents a ChangeTypeV1 in the context of its usage, e.g.
    bound to a RoleV1. The relevant part is not the role though, but the approvers
    defined in that context.

    ChangeTypeContext serves as a way to reason about changes within an
    arbitrary context, as long as it provides approvers.

    The `context` property is a textual representation of context the ChangeTypeV1
    operates in. It is used mostly during logging and reporting to provide
    readable feedback about why a ChangeTypeV1 was applied to certain changes.
    """

    change_type_processor: ChangeTypeProcessor
    context: str
    approvers: list[Approver]
    context_file: FileRef

    @property
    def disabled(self) -> bool:
        return self.change_type_processor.disabled


JSON_PATH_ROOT = "$"


def change_path_covered_by_allowed_path(changed_path: str, allowed_path: str) -> bool:
    return changed_path.startswith(allowed_path) or allowed_path == JSON_PATH_ROOT
