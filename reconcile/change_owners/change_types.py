from collections import defaultdict
from collections.abc import (
    MutableMapping,
    Sequence,
)
from dataclasses import (
    dataclass,
    field,
)
from enum import Enum
from typing import (
    Any,
    Optional,
)

import anymarkup
import jinja2
import jinja2.meta
import jsonpath_ng
import jsonpath_ng.ext
import networkx

from reconcile.change_owners.approver import Approver
from reconcile.change_owners.bundle import (
    BundleFileType,
    FileRef,
)
from reconcile.change_owners.diff import (
    SHA256SUM_FIELD_NAME,
    SHA256SUM_PATH,
    Diff,
    DiffType,
    extract_diffs,
)
from reconcile.gql_definitions.change_owners.queries.change_types import (
    ChangeTypeChangeDetectorJsonPathProviderV1,
    ChangeTypeChangeDetectorV1,
    ChangeTypeImplicitOwnershipV1,
    ChangeTypeV1,
)


class ChangeTypePriority(Enum):
    """
    The order of the priorities is important. They are listed in decreasing priority.
    """

    CRITICAL = "critical"
    URGENT = "urgent"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


def parent_of_jsonpath(path: jsonpath_ng.JSONPath) -> Optional[jsonpath_ng.JSONPath]:
    # todo - figure out if this is enough of if we have other
    # structures where a parent can be extracted
    if isinstance(path, jsonpath_ng.Child):
        return path.left
    else:
        return None


@dataclass
class DiffCoverage:
    diff: Diff
    coverage: list["ChangeTypeContext"]

    # if a diff is split into smaller diffs, they are stored here
    # please notice that the splits are DiffCoverages objects themselves which
    # can have splits on their own. DiffCoverage objects form a tree-like structure
    _split_into: list["DiffCoverage"] = field(default_factory=list)

    def is_covered(self) -> bool:
        """
        a diff is considered covered,
        * if there is at least one change-type that covers the diff entirely
        * if there the diff is split into smaller diffs which are covered.
          the smaller diffs must cover the entire original diff in sum
        """
        return self.is_directly_covered() or self.is_covered_by_splits()

    def is_directly_covered(self) -> bool:
        return any(not ctx.disabled for ctx in self.coverage)

    def is_covered_by_splits(self) -> bool:
        """
        determine if the splits of this DiffCoverage would cover it entirely
        """
        # remove the parts of this diffs data that are covered by the splits
        # if nothing remains, the splits cover the entire diff
        uncovered_data = self.diff.get_context_data_copy()
        if uncovered_data and isinstance(uncovered_data, MutableMapping):
            for s in self._split_into:
                if s.is_covered():
                    # this removes the data that matches the path
                    s.diff.path.filter(lambda x: True, uncovered_data)
                    # remove empty parents recursively
                    parent_path = s.diff.path
                    while parent_path := parent_of_jsonpath(parent_path):
                        for parent_data in parent_path.find(uncovered_data):
                            if not parent_data.value:
                                parent_path.filter(lambda x: True, uncovered_data)
        return uncovered_data == {}

    def changed_path_covered_by_path(self, path: jsonpath_ng.JSONPath) -> bool:
        return str(self.diff.path).startswith(str(path)) or path == jsonpath_ng.Root()

    def path_under_changed_path(self, path: jsonpath_ng.JSONPath) -> bool:
        return (
            str(path).startswith(str(self.diff.path))
            or str(self.diff.path) == JSON_PATH_ROOT
        ) and path != str(self.diff.path)

    def split(
        self, path: jsonpath_ng.JSONPath, ctx: "ChangeTypeContext"
    ) -> Optional["DiffCoverage"]:
        """
        create a new DiffCoverage object that coveres the given path
        this function also manages the split tree structure in _split_into
        so that finer diffs are always lower in the tree that higher diffs.
        """
        if self.path_under_changed_path(path):
            # find out if the path fits unter an existing split
            for s in self._split_into:
                if sub_cov := s.split(path, ctx):
                    return sub_cov

            # no suitable existing split found, create a new one
            split_sub_coverage = DiffCoverage(
                self.diff.create_subdiff(path), self.coverage.copy()
            )

            # consolidate existing splits. maybe they should go under the newly created one?
            consolidated_splits = [split_sub_coverage]
            for s in self._split_into:
                if split_sub_coverage.path_under_changed_path(s.diff.path_str()):
                    split_sub_coverage._split_into.append(s)
                else:
                    consolidated_splits.append(s)

            # add the covering context to the new split and all its child splits
            split_sub_coverage.add_covering_context(ctx)

            self._split_into = consolidated_splits
            return split_sub_coverage
        if self.diff.path == path:
            return self
        else:
            return None

    def add_covering_context(self, ctx: "ChangeTypeContext"):
        self.coverage.append(ctx)
        for s in self._split_into:
            s.add_covering_context(ctx)

    def fine_grained_diff_coverages(self) -> dict[str, "DiffCoverage"]:
        coverages = {}
        for s in self._split_into:
            coverages.update(s.fine_grained_diff_coverages())

        # if this diff is not directly covered by a change-type, but is covered
        # by the splits, this DiffCoverage is discarded because it bears no value
        # in the coverage process, e.g. for a newly introduced file, the high
        # level diff is usually '$', which is very rough and might not be covered
        # by any change-type. the splits of that diff, however, are more fine
        # and are covered by change-types. so it makes sense to just keep the splits
        # and discard the high level '$' diff. it would even prevent a change
        # from being self-serviceable.
        if not (not self.is_directly_covered() and self.is_covered_by_splits()):
            coverages[self.diff.path_str()] = self

        return coverages


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
    diffs: list[Diff]
    _diff_coverage: dict[str, DiffCoverage] = field(init=False, default_factory=dict)

    def __post_init__(self) -> None:
        self._diff_coverage = {d.path_str(): DiffCoverage(d, []) for d in self.diffs}

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
            contextSchema: /access/role-1.yml

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
                    if dc.changed_path_covered_by_path(allowed_path):
                        covered_diffs[dc.diff.path_str()] = dc.diff
                        dc.coverage.append(change_type_context)
                    elif SHA256SUM_PATH != allowed_path and dc.path_under_changed_path(
                        allowed_path
                    ):
                        # the self-service path allowed by the change-type is covering
                        # only parts of the diff. we will split the diff into a
                        # smaller part, that can be covered by the change-type.
                        # but the rest of the diff needs to be covered by another
                        # change-type, either in full or again as a split.
                        sub_dc = dc.split(allowed_path, change_type_context)
                        if not sub_dc:
                            raise Exception(
                                f"unable to create a subdiff for path {allowed_path} on diff {dc.diff.path_str()}"
                            )
                        covered_diffs[str(allowed_path)] = sub_dc.diff

        return covered_diffs

    def _filter_diffs(self, diff_types: list[DiffType]) -> list[DiffCoverage]:
        return [
            d for d in self._diff_coverage.values() if d.diff.diff_type in diff_types
        ]

    def all_changes_covered(self) -> bool:
        return all(d.is_covered() for d in self.diff_coverage)

    def raw_diff_count(self) -> int:
        return len(self._diff_coverage)

    @property
    def diff_coverage(self) -> Sequence[DiffCoverage]:
        """
        returns the meaningful set of diffs, potentially more fine grained than
        what was originally detected for to the BundleFileChange.
        """
        coverages: list[DiffCoverage] = []
        for dc in self._diff_coverage.values():
            coverages.extend(dc.fine_grained_diff_coverages().values())
        return coverages

    def involved_change_types(self) -> list["ChangeTypeProcessor"]:
        """
        returns all the change-types that are involved in the coverage
        of all changes
        """
        change_types = []
        for dc in self.diff_coverage:
            for ctx in dc.coverage:
                change_types.append(ctx.change_type_processor)
        return change_types


def parse_resource_file_content(content: Optional[Any]) -> tuple[Any, Optional[str]]:
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
            diffs=diffs,
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
    description: str
    priority: ChangeTypePriority
    context_type: BundleFileType
    context_schema: Optional[str]
    disabled: bool
    implicit_ownership: list[ChangeTypeImplicitOwnershipV1]

    def __post_init__(self):
        self._expressions_by_file_type_schema: dict[
            tuple[BundleFileType, Optional[str]], list[PathExpression]
        ] = defaultdict(list)
        self._changes: list[ChangeTypeChangeDetectorV1] = []

    @property
    def changes(self) -> Sequence[ChangeTypeChangeDetectorV1]:
        return self._changes

    def allowed_changed_paths(
        self, file_ref: FileRef, file_content: Any, ctx: "ChangeTypeContext"
    ) -> list[jsonpath_ng.JSONPath]:
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
                        p.full_path
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
        description=change_type.description,
        priority=ChangeTypePriority(change_type.priority),
        context_type=BundleFileType[change_type.context_type.upper()],
        context_schema=change_type.context_schema,
        disabled=bool(change_type.disabled),
        implicit_ownership=change_type.implicit_ownership or [],
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


def get_priority_for_changes(
    bundle_file_changes: list[BundleFileChange],
) -> Optional[ChangeTypePriority]:
    """
    Finds the lowest priority of all change types involved in the provided bundle file changes.
    """
    priorities: set[ChangeTypePriority] = set()
    for bfc in bundle_file_changes:
        for ct in bfc.involved_change_types():
            priorities.add(ct.priority)
    # get the lowest priority
    for p in reversed(ChangeTypePriority):
        if p in priorities:
            return p
    return None
