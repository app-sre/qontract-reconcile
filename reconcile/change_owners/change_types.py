from abc import (
    ABC,
    abstractmethod,
)
from collections import defaultdict
from collections.abc import (
    MutableMapping,
    Sequence,
    Set,
)
from dataclasses import (
    dataclass,
    field,
)
from enum import Enum
from typing import (
    Any,
    Optional,
    Tuple,
)

import jinja2
import jinja2.meta
import jsonpath_ng
import networkx

from reconcile.change_owners.approver import (
    Approver,
    ApproverReachability,
)
from reconcile.change_owners.bundle import (
    BundleFileType,
    FileDiffResolver,
    FileRef,
)
from reconcile.change_owners.diff import Diff
from reconcile.gql_definitions.change_owners.queries.change_types import (
    ChangeTypeChangeDetectorChangeTypeProviderV1,
    ChangeTypeChangeDetectorJsonPathProviderV1,
    ChangeTypeImplicitOwnershipV1,
    ChangeTypeV1,
)
from reconcile.utils.jsonpath import (
    parse_jsonpath,
    remove_prefix_from_path,
    sortable_jsonpath_string_repr,
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
    return None


@dataclass
class DiffCoverage:
    diff: Diff
    coverage: list["ChangeTypeContext"]

    # if a diff is split into smaller diffs, they are stored here
    # please notice that the splits are DiffCoverages objects themselves which
    # can have splits on their own. DiffCoverage objects form a tree-like structure
    _split_into: list["DiffCoverage"] = field(default_factory=list)

    parent: Optional["DiffCoverage"] = None

    @property
    def change_owner_labels(self) -> set[str]:
        """
        Returns a list of change-owner labels of all involved change-type contexts.
        """
        labels = {label for c in self.coverage for label in c.change_owner_labels or {}}
        for _split in self._split_into:
            labels.update(_split.change_owner_labels)
        return labels

    def relative_path(self) -> jsonpath_ng.JSONPath:
        if self.parent:
            path = remove_prefix_from_path(self.diff.path, self.parent.diff.path)
            if not path:
                # this can't happen, the parent path is always a prefix of the child path
                # but we need to make mypy happy so lets raise an exception that will
                # never be raised
                raise ValueError(
                    "Diff split seems not to be under its parent change. "
                    "This can only happen due to a bug in change-owners. "
                    "Happy bug hunting!"
                )
            return path
        return self.diff.path

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
            # sort splits so that later indices are always removed before earlier ones
            sorted_splits = sorted(
                self._split_into,
                key=lambda x: sortable_jsonpath_string_repr(x.diff.path, 5),
                reverse=True,
            )
            for s in sorted_splits:
                if s.is_covered():
                    relative_path = s.relative_path()
                    # this removes the data that matches the path
                    relative_path.filter(lambda x: True, uncovered_data)
                    # remove empty parents iteratively
                    parent_path = relative_path
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
        ) and str(path) != str(self.diff.path)

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
                diff=self.diff.create_subdiff(path),
                coverage=self.coverage.copy(),
                parent=self,
            )

            # consolidate existing splits. maybe they should go under the newly created one?
            consolidated_splits = [split_sub_coverage]
            for s in self._split_into:
                if split_sub_coverage.path_under_changed_path(s.diff.path_str()):
                    s.parent = split_sub_coverage
                    split_sub_coverage._split_into.append(s)
                else:
                    s.parent = self
                    consolidated_splits.append(s)

            # add the covering context to the new split and all its child splits
            split_sub_coverage.add_covering_context(ctx)

            self._split_into = consolidated_splits
            return split_sub_coverage

        if self.diff.path == path:
            self.add_covering_context(ctx)
            return self

        return None

    def add_covering_context(self, ctx: "ChangeTypeContext") -> None:
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
            self.parsed_jsonpath = parse_jsonpath(jsonpath_expression)

    def jsonpath_for_context(self, ctx: "ChangeTypeContext") -> jsonpath_ng.JSONPath:
        if self.parsed_jsonpath:
            return self.parsed_jsonpath

        expr = self.template.render({
            self.CTX_FILE_PATH_VAR_NAME: ctx.context_file.path,
        })
        return parse_jsonpath(expr)

    def __eq__(self, obj: object) -> bool:
        return (
            isinstance(obj, PathExpression)
            and obj.jsonpath_expression == self.jsonpath_expression
        )


@dataclass
class FileChange:
    file_ref: FileRef
    old: Optional[dict[str, Any]]
    new: Optional[dict[str, Any]]
    old_backrefs: set[FileRef] = field(default_factory=set)
    new_backrefs: set[FileRef] = field(default_factory=set)


class OwnershipContext(ABC):
    @abstractmethod
    def find_ownership_context(
        self,
        context_schema: Optional[str],
        change: FileChange,
    ) -> list[FileRef]: ...


@dataclass
class ForwardrefOwnershipContext(OwnershipContext):
    selector: jsonpath_ng.JSONPath
    when: Optional[str] = None

    def find_ownership_context(
        self,
        context_schema: Optional[str],
        change: FileChange,
    ) -> list[FileRef]:
        old_contexts = {e.value for e in self.selector.find(change.old)}
        new_contexts = {e.value for e in self.selector.find(change.new)}

        # apply conditions
        if self.when == "added":
            affected_context_paths = new_contexts - old_contexts
        elif self.when == "removed":
            affected_context_paths = old_contexts - new_contexts
        elif self.when is None and old_contexts == new_contexts:
            affected_context_paths = old_contexts
        else:
            affected_context_paths = set()

        return [
            FileRef(
                schema=context_schema,
                path=path,
                file_type=BundleFileType.DATAFILE,
            )
            for path in affected_context_paths
        ]


@dataclass
class BackrefOwnershipContext(OwnershipContext):
    selector: jsonpath_ng.JSONPath
    file_diff_resolver: FileDiffResolver
    when: Optional[str] = None

    def find_ownership_context(
        self,
        context_schema: Optional[str],
        change: FileChange,
    ) -> list[FileRef]:
        # get backref datafile content
        backref_datafile_content = {
            ref: self.file_diff_resolver.lookup_file_diff(ref)
            for ref in change.old_backrefs.union(change.new_backrefs)
        }

        # extract contexts
        # we only care for those backrefs that mention the changed file at the selector
        old_contexts = {
            ref
            for ref, data in backref_datafile_content.items()
            if any(f.value == change.file_ref.path for f in self.selector.find(data[0]))
        }
        new_contexts = {
            ref
            for ref, data in backref_datafile_content.items()
            if any(f.value == change.file_ref.path for f in self.selector.find(data[1]))
        }

        # apply conditions
        if self.when == "added":
            return list(new_contexts.difference(old_contexts))
        if self.when == "removed":
            return list(old_contexts.difference(new_contexts))
        if self.when is None and old_contexts == new_contexts:
            return list(old_contexts)
        return []


@dataclass
class ContextExpansion:
    """
    Represents a context expansion configuration, capable of hopping from one
    context of a change-type to another context of another change-type.
    """

    context: OwnershipContext
    change_type: "ChangeTypeProcessor"
    file_diff_resolver: FileDiffResolver

    def expand_from_file_ref(
        self,
        file_ref: FileRef,
        expansion_trail: Set[Tuple[str, FileRef]],
    ) -> list["ResolvedContext"]:
        old_data, new_data = self.file_diff_resolver.lookup_file_diff(file_ref)
        return self.expand(
            FileChange(
                file_ref=file_ref,
                old=old_data,
                new=new_data,
            ),
            expansion_trail,
        )

    def expand(
        self,
        change: FileChange,
        expansion_trail: Set[Tuple[str, FileRef]],
    ) -> list["ResolvedContext"]:
        """
        Find context based on the `self.context`, lookup the file diff for
        that new context and expose everything as a new `ResolvedContext` with
        `self.change_type` as the change type.
        """
        context_file_refs = self.context.find_ownership_context(
            context_schema=self.change_type.context_schema,
            change=change,
        )
        expaned_context_file_refs: list["ResolvedContext"] = []
        for ref in context_file_refs:
            ref_old_data, ref_new_data = self.file_diff_resolver.lookup_file_diff(ref)
            expaned_context_file_refs.extend(
                self.change_type.find_context_file_refs(
                    change=FileChange(
                        file_ref=ref,
                        old=ref_old_data,
                        new=ref_new_data,
                    ),
                    expansion_trail=expansion_trail,
                )
            )
        return expaned_context_file_refs


@dataclass
class ResolvedContext:
    """
    The result of a context resolution. It is used for all kinds of context
    and ownership resolution processes, including the context expansion process.
    """

    owned_file_ref: FileRef
    context_file_ref: FileRef
    change_type: "ChangeTypeProcessor"


@dataclass
class ChangeDetector(ABC):
    """
    Represents an item from a change-types `change` list.
    """

    context_schema: Optional[str]
    change_schema: Optional[str]
    context: Optional[OwnershipContext]

    @abstractmethod
    def find_context_file_refs(
        self,
        change: FileChange,
    ) -> list[FileRef]: ...


@dataclass
class JsonPathChangeDetector(ChangeDetector):
    json_path_selectors: list[str]

    def __post_init__(self) -> None:
        self._json_path_expressions = [
            PathExpression(jsonpath_expression)
            for jsonpath_expression in self.json_path_selectors
        ]

    @property
    def json_path_expressions(self) -> list[PathExpression]:
        return self._json_path_expressions

    def find_context_file_refs(
        self,
        change: FileChange,
    ) -> list[FileRef]:
        if self.context:
            return self.context.find_ownership_context(
                context_schema=self.context_schema,
                change=change,
            )
        return []


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
    restrictive: Optional[bool] = False

    def __post_init__(self) -> None:
        self._expressions_by_file_type_schema: dict[
            tuple[BundleFileType, Optional[str]], list[PathExpression]
        ] = defaultdict(list)
        self._change_detectors: list[ChangeDetector] = []
        self._context_expansions: list[ContextExpansion] = []
        self._heritage: set[str] = set()

    @property
    def change_detectors(self) -> Sequence[ChangeDetector]:
        return self._change_detectors

    def find_context_file_refs(
        self,
        change: FileChange,
        expansion_trail: Set[Tuple[str, FileRef]],
    ) -> list[ResolvedContext]:
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
        contexts: list[ResolvedContext] = []

        # prevent infinite ownership resolution
        expansion_trail_copy = set(expansion_trail)
        if (self.name, change.file_ref) in expansion_trail_copy:
            return contexts

        expansion_trail_copy.add((self.name, change.file_ref))

        # direct context extraction
        # the changed file itself is giving the context for approver extraction
        # see doc string for more details
        if self.context_schema is None or self.context_schema == change.file_ref.schema:
            contexts.append(
                ResolvedContext(
                    owned_file_ref=change.file_ref,
                    context_file_ref=change.file_ref,
                    change_type=self,
                )
            )

            # expand context based on change-type composition
            for ce in self._context_expansions:
                for ec in ce.expand(change, expansion_trail_copy):
                    # add expanded contexts (derived owned files)
                    contexts.append(
                        ResolvedContext(
                            owned_file_ref=ec.owned_file_ref,
                            context_file_ref=change.file_ref,
                            change_type=ec.change_type,
                        )
                    )

        # context detection
        # the context for approver extraction can be found within the changed
        # file with a `context.selector`
        # see doc string for more details
        for c in self.change_detectors:
            if c.change_schema == change.file_ref.schema:
                for ctx_file_ref in c.find_context_file_refs(change):
                    contexts.append(
                        ResolvedContext(
                            owned_file_ref=ctx_file_ref,
                            context_file_ref=ctx_file_ref,
                            change_type=self,
                        )
                    )
                    for ce in self._context_expansions:
                        for ec in ce.expand_from_file_ref(
                            ctx_file_ref, expansion_trail_copy
                        ):
                            # add expanded contexts (derived owned files)
                            contexts.append(
                                ResolvedContext(
                                    owned_file_ref=ec.owned_file_ref,
                                    context_file_ref=ctx_file_ref,
                                    change_type=ec.change_type,
                                )
                            )

        return contexts

    def allowed_changed_paths(
        self, file_ref: FileRef, file_content: Any, ctx: "ChangeTypeContext"
    ) -> list[jsonpath_ng.JSONPath]:
        """
        find all paths within the provide file_content, that are covered by this
        ChangeTypeV1. the paths are represented as jsonpath expressions pinpointing
        the root element that can be changed
        """
        paths = self._allowed_changed_paths_for_file_type_and_schema(
            file_ref.file_type, file_ref.schema, file_content, ctx
        )

        # lets also check for allowed paths that are not specific to a schema
        for p in self._allowed_changed_paths_for_file_type_and_schema(
            file_ref.file_type, None, file_content, ctx
        ):
            if p not in paths:
                paths.append(p)
        return paths

    def _allowed_changed_paths_for_file_type_and_schema(
        self,
        file_type: BundleFileType,
        file_schema: Optional[str],
        file_content: Any,
        ctx: "ChangeTypeContext",
    ) -> list[jsonpath_ng.JSONPath]:
        paths = []
        if (
            file_type,
            file_schema,
        ) in self._expressions_by_file_type_schema:
            for change_type_path_expression in self._expressions_by_file_type_schema[
                (file_type, file_schema)
            ]:
                paths.extend([
                    p.full_path
                    for p in change_type_path_expression.jsonpath_for_context(ctx).find(
                        file_content
                    )
                ])
        return paths

    def add_change_detector(
        self,
        detector: ChangeDetector,
    ) -> None:
        if isinstance(detector, JsonPathChangeDetector):
            self._change_detectors.append(detector)
            change_schema = detector.change_schema or self.context_schema
            expressions = self._expressions_by_file_type_schema[
                (self.context_type, change_schema)
            ]
            for path_expression in detector.json_path_expressions:
                if path_expression not in expressions:
                    expressions.append(path_expression)
        else:
            raise ValueError(
                f"{type(detector)} is not a supported change detection provider within ChangeTypes"
            )

    def add_context_expansion(self, context_expansion: ContextExpansion) -> None:
        self._context_expansions.append(context_expansion)

    def inherit_from(self, other: "ChangeTypeProcessor") -> None:
        for detector in other.change_detectors:
            self.add_change_detector(detector)
        other._heritage = self.lineage.union(other._heritage)

    @property
    def lineage(self) -> set[str]:
        return self._heritage.union({self.name})


def build_ownership_context(
    file_diff_resolver: FileDiffResolver,
    selector: jsonpath_ng.JSONPath,
    when: Optional[str] = None,
    where: Optional[str] = None,
) -> OwnershipContext:
    """
    create an OwnershipContext object based on the provided parameters
    """
    if where == "backrefs":
        return BackrefOwnershipContext(
            file_diff_resolver=file_diff_resolver, selector=selector, when=when
        )
    return ForwardrefOwnershipContext(selector=selector, when=when)


def init_change_type_processors(
    change_types: Sequence[ChangeTypeV1], file_diff_resolver: FileDiffResolver
) -> dict[str, ChangeTypeProcessor]:
    processors: dict[str, ChangeTypeProcessor] = {}

    change_type_inheritance_graph = networkx.DiGraph()

    for change_type in change_types:
        # build raw change-type-processor
        processors[change_type.name] = ChangeTypeProcessor(
            name=change_type.name,
            description=change_type.description,
            priority=ChangeTypePriority(change_type.priority),
            context_type=BundleFileType[change_type.context_type.upper()],
            context_schema=change_type.context_schema,
            disabled=bool(change_type.disabled),
            restrictive=bool(change_type.restrictive),
            implicit_ownership=change_type.implicit_ownership or [],
        )
        # register inheritance edges for cycle detection
        change_type_inheritance_graph.add_node(change_type.name)
        for i in change_type.inherit or []:
            change_type_inheritance_graph.add_edge(change_type.name, i.name)

    # register change detectors
    for change_type in change_types:
        processor = processors[change_type.name]
        for change_detector in change_type.changes or []:
            if isinstance(change_detector, ChangeTypeChangeDetectorJsonPathProviderV1):
                ownership_context = None
                if change_detector.context:
                    ownership_context = build_ownership_context(
                        file_diff_resolver=file_diff_resolver,
                        selector=parse_jsonpath(change_detector.context.selector),
                        when=change_detector.context.when,
                        where=change_detector.context.where,
                    )
                processor.add_change_detector(
                    JsonPathChangeDetector(
                        context_schema=processor.context_schema,
                        change_schema=change_detector.change_schema
                        or processor.context_schema,
                        json_path_selectors=change_detector.json_path_selectors,
                        context=ownership_context,
                    )
                )
            elif isinstance(
                change_detector, ChangeTypeChangeDetectorChangeTypeProviderV1
            ):
                # change type composition is defined on the higher level change-type,
                # e.g. the app-owner change-type. in code, this composition relationship
                # is tracked on the reused change-type, e.g. the namespace-owner change-type.
                #
                # this makes it easier to trace a change back from it's original context
                # to the higher level change-type
                for ct in change_detector.change_types:
                    processors[ct.name].add_context_expansion(
                        ContextExpansion(
                            change_type=processor,
                            context=build_ownership_context(
                                file_diff_resolver=file_diff_resolver,
                                selector=parse_jsonpath(
                                    change_detector.ownership_context.selector
                                ),
                                when=change_detector.ownership_context.when,
                                where=change_detector.ownership_context.where,
                            ),
                            file_diff_resolver=file_diff_resolver,
                        )
                    )

    #
    # V A L I D A T E
    #

    # detect inheritance cycles
    if cycles := list(networkx.simple_cycles(change_type_inheritance_graph)):
        raise ChangeTypeCycleError("Cycles detected in change-type inheritance", cycles)

    #
    # A G G R E G A T I O N
    #

    # aggregate inherited changes
    for ctp in processors.values():
        for d in networkx.descendants(change_type_inheritance_graph, ctp.name):
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

            # the higher level change type adopts the change detectors from his decentents
            ctp.inherit_from(processors[d])

            # the decentents adopt the context expansions from the higher level change type
            for ce in ctp._context_expansions:
                processors[d].add_context_expansion(ce)

    return processors


class ChangeTypeIncompatibleInheritanceError(ValueError):
    pass


class ChangeTypeCycleError(ValueError):
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
    origin: str
    context_file: FileRef
    approvers: list[Approver]
    approver_reachability: Optional[list[ApproverReachability]] = None
    change_owner_labels: Optional[set[str]] = None

    @property
    def disabled(self) -> bool:
        return self.change_type_processor.disabled

    def includes_approver(self, approver_name: str) -> bool:
        return (
            next((a for a in self.approvers if a.org_username == approver_name), None)
            is not None
        )


JSON_PATH_ROOT = "$"


def change_path_covered_by_allowed_path(changed_path: str, allowed_path: str) -> bool:
    return changed_path.startswith(allowed_path) or allowed_path == JSON_PATH_ROOT
