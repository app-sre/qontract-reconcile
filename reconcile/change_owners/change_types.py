from dataclasses import dataclass
from collections import defaultdict
from enum import Enum
from typing import Any, Iterable, Optional, Tuple


import jsonpath_ng
import jsonpath_ng.ext
import anymarkup

from reconcile.change_owners.diff import (
    SHA256SUM_FIELD_NAME,
    Diff,
    DiffType,
    extract_diffs,
)
from reconcile.gql_definitions.change_owners.queries.change_types import (
    ChangeTypeV1,
    ChangeTypeChangeDetectorJsonPathProviderV1,
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

    def extract_context_file_refs(self, change_type: ChangeTypeV1) -> list[FileRef]:
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
                self.fileref, file_content
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


def parse_resource_file_content(content: Optional[Any]) -> Any:
    if content:
        try:
            return anymarkup.parse(content, force_types=None)
        except Exception:
            # not parsable content - we will just deal with the plain content
            return content
    else:
        return None


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

    # try to parse the content if a resourcefile has a schema
    if file_type == BundleFileType.RESOURCEFILE and schema:
        old_file_content = parse_resource_file_content(old_file_content)
        new_file_content = parse_resource_file_content(new_file_content)
    diffs = extract_diffs(
        schema=schema,
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


@dataclass
class ChangeTypeProcessor:
    """
    ChangeTypeProcessor wraps the generated GQL class ChangeTypeV1 and adds
    functionality that operates close on the configuration of the ChangeTypeV1,
    like computing the jsonpaths that are allowed to change in a file.
    """

    change_type: ChangeTypeV1
    expressions_by_file_type_schema: dict[
        Tuple[BundleFileType, Optional[str]], list[jsonpath_ng.JSONPath]
    ]

    def allowed_changed_paths(self, file_ref: FileRef, file_content: Any) -> list[str]:
        """
        find all paths within the provide file_content, that are covered by this
        ChangeTypeV1. the paths are represented as jsonpath expressions pinpointing
        the root element that can be changed
        """
        paths = []
        if (
            file_ref.file_type,
            file_ref.schema,
        ) in self.expressions_by_file_type_schema:
            for change_type_path_expression in self.expressions_by_file_type_schema[
                (file_ref.file_type, file_ref.schema)
            ]:
                paths.extend(
                    [
                        str(p.full_path)
                        for p in change_type_path_expression.find(file_content)
                    ]
                )
        return paths


def build_change_type_processor(change_type: ChangeTypeV1) -> ChangeTypeProcessor:
    """
    Build a ChangeTypeProcessor from a ChangeTypeV1 and pre-initializing jsonpaths.
    """
    expressions_by_file_type_schema: dict[
        Tuple[BundleFileType, Optional[str]], list[jsonpath_ng.JSONPath]
    ] = defaultdict(list)
    for c in change_type.changes:
        if isinstance(c, ChangeTypeChangeDetectorJsonPathProviderV1):
            change_schema = c.change_schema or change_type.context_schema
            if change_schema:
                for jsonpath_expression in c.json_path_selectors + [
                    f"'{SHA256SUM_FIELD_NAME}'"
                ]:
                    file_type = BundleFileType[change_type.context_type.upper()]
                    expressions_by_file_type_schema[(file_type, change_schema)].append(
                        jsonpath_ng.ext.parse(jsonpath_expression)
                    )
        else:
            raise ValueError(
                f"{c.provider} is not a supported change detection provider within ChangeTypes"
            )
    return ChangeTypeProcessor(
        change_type=change_type,
        expressions_by_file_type_schema=expressions_by_file_type_schema,
    )


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

    @property
    def disabled(self) -> bool:
        return bool(self.change_type_processor.change_type.disabled)


JSON_PATH_ROOT = "$"


def change_path_covered_by_allowed_path(changed_path: str, allowed_path: str) -> bool:
    return changed_path.startswith(allowed_path) or allowed_path == JSON_PATH_ROOT
