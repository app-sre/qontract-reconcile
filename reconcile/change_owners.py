from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional, Protocol, Tuple
from functools import reduce
import json
import logging
import traceback
import re

from reconcile.utils.output import print_table
from reconcile.utils import gql
from reconcile.gql_definitions.change_owners.queries.self_service_roles import RoleV1
from reconcile.gql_definitions.change_owners.queries.change_types import (
    ChangeTypeV1,
    ChangeTypeChangeDetectorJsonPathProviderV1,
)
from reconcile.gql_definitions.change_owners.queries import (
    self_service_roles,
    change_types,
)
from reconcile.utils.semver_helper import make_semver

from deepdiff import DeepDiff
from deepdiff.helper import CannotCompare
from deepdiff.model import DiffLevel

import jsonpath_ng
import jsonpath_ng.ext
import anymarkup


QONTRACT_INTEGRATION = "change-owners"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)


class BundleFileType(Enum):
    DATAFILE = "datafile"
    RESOURCEFILE = "resourcefile"


@dataclass(frozen=True)
class FileRef:
    file_type: BundleFileType
    path: str
    schema: Optional[str]


class DiffType(Enum):
    ADDED = "added"
    REMOVED = "removed"
    CHANGED = "changed"


@dataclass
class Diff:
    """
    A change within a file, pinpointing the location of the change with a jsonpath.
    """

    path: jsonpath_ng.JSONPath
    diff_type: DiffType
    old: Optional[Any]
    new: Optional[Any]
    covered_by: list["ChangeTypeContext"]

    def old_value_repr(self) -> Optional[str]:
        return self._value_repr(self.old)

    def new_value_repr(self) -> Optional[str]:
        return self._value_repr(self.new)

    def _value_repr(self, value: Optional[Any]) -> Optional[str]:
        if value:
            if isinstance(value, (dict, list)):
                return json.dumps(value, indent=2)
            else:
                return str(value)
        return value


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

        The change contexts that cover a change, are registered within the
        `Diff` objects `covered_by` list.
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
        diffs: list[Diff],
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
                for d in diffs:
                    covered = str(d.path).startswith(allowed_path)
                    if covered:
                        covered_diffs[str(d.path)] = d
                        d.covered_by.append(change_type_context)
        return covered_diffs

    def _filter_diffs(self, diff_types: list[DiffType]) -> list[Diff]:
        return list(filter(lambda d: d.diff_type in diff_types, self.diffs))


IDENTIFIER_FIELD_NAME = "__identifier"
REF_FIELD_NAME = "$ref"


def _extract_identifier_from_object(obj: Any) -> Optional[str]:
    if isinstance(obj, dict):
        if IDENTIFIER_FIELD_NAME in obj:
            return obj.get(IDENTIFIER_FIELD_NAME)
        elif REF_FIELD_NAME in obj and len(obj) == 1:
            return obj.get(REF_FIELD_NAME)
    return None


def compare_object_ctx_identifier(
    x: Any, y: Any, level: Optional[DiffLevel] = None
) -> bool:
    """
    this function helps the deepdiff library to decide if two objects are
    actually the same in the sense of identity. this helps with finding
    changes in lists where reordering of items might occure.
    the __identifier key of an object is maintained by the qontract-validator
    based on the contextUnique flags on properties in jsonschemas of qontract-schema.

    in a list of heterogenous elements (e.g. openshiftResources), not every element
    necessarily has an __identitry property, e.g. vault-secret elements have one,
    but resource-template elements don't (because there is no set of properties
    clearly identifying the resulting resource). this is fine!

    if two objects have identities, they can be used to figure out if they are
    the same object.

    if only one of them has an identity, they are clearly not the same object.

    if two objects with no identity properties are compared, deepdiff will still
    try to figure out if they might be the same object based on a critical number
    of matching properties and values. this situation is signaled back to
    deepdiff by raising the CannotCompare exception.
    """
    x_id = _extract_identifier_from_object(x)
    y_id = _extract_identifier_from_object(y)
    if x_id and y_id:
        # if both have an identifier, they are the same if the identifiers are the same
        return x_id == y_id
    if x_id or y_id:
        # if only one of them has an identifier, they must be different objects
        return False
    # detecting if two objects without identifiers are the same, is beyond this
    # functions capability, hence it tells deepdiff to figure it out on its own
    raise CannotCompare() from None


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
        if old_file_content:
            old_file_content = anymarkup.parse(old_file_content, force_types=None)
        if new_file_content:
            new_file_content = anymarkup.parse(new_file_content, force_types=None)

    diffs: list[Diff] = []
    if old_file_content and new_file_content:
        deep_diff = DeepDiff(
            old_file_content,
            new_file_content,
            ignore_order=True,
            iterable_compare_func=compare_object_ctx_identifier,
            cutoff_intersection_for_pairs=1,
        )

        # handle changed values
        diffs.extend(
            [
                Diff(
                    path=deepdiff_path_to_jsonpath(path),
                    diff_type=DiffType.CHANGED,
                    old=change.get("old_value"),
                    new=change.get("new_value"),
                    covered_by=[],
                )
                for path, change in deep_diff.get("values_changed", {}).items()
            ]
        )
        # handle property added
        for path in deep_diff.get("dictionary_item_added", []):
            jpath = deepdiff_path_to_jsonpath(path)
            change = jpath.find(new_file_content)
            change_value = change[0].value if change else None
            diffs.append(
                Diff(
                    path=jpath,
                    diff_type=DiffType.ADDED,
                    old=None,
                    new=change_value,
                    covered_by=[],
                )
            )
        # handle property removed
        for path in deep_diff.get("dictionary_item_removed", []):
            jpath = deepdiff_path_to_jsonpath(path)
            change = jpath.find(old_file_content)
            change_value = change[0].value if change else None
            diffs.append(
                Diff(
                    path=jpath,
                    diff_type=DiffType.REMOVED,
                    old=change_value,
                    new=None,
                    covered_by=[],
                )
            )
        # handle added items
        diffs.extend(
            [
                Diff(
                    path=deepdiff_path_to_jsonpath(path),
                    diff_type=DiffType.ADDED,
                    old=None,
                    new=change,
                    covered_by=[],
                )
                for path, change in deep_diff.get("iterable_item_added", {}).items()
            ]
        )
        # handle removed items
        diffs.extend(
            [
                Diff(
                    path=deepdiff_path_to_jsonpath(path),
                    diff_type=DiffType.REMOVED,
                    old=change,
                    new=None,
                    covered_by=[],
                )
                for path, change in deep_diff.get("iterable_item_removed", {}).items()
            ]
        )
    elif old_file_content:
        # file was deleted
        diffs.append(
            Diff(
                path=jsonpath_ng.Root(),
                diff_type=DiffType.REMOVED,
                old=old_file_content,
                new=None,
                covered_by=[],
            )
        )
    elif new_file_content:
        # file was added
        diffs.append(
            Diff(
                path=jsonpath_ng.Root(),
                diff_type=DiffType.ADDED,
                old=None,
                new=new_file_content,
                covered_by=[],
            )
        )

    if diffs:
        return BundleFileChange(
            fileref=fileref, old=old_file_content, new=new_file_content, diffs=diffs
        )
    else:
        return None


DEEP_DIFF_RE = re.compile(r"\['?(.*?)'?\]")


def deepdiff_path_to_jsonpath(deep_diff_path: str) -> jsonpath_ng.JSONPath:
    """
    deepdiff's way to describe a path within a data structure differs from jsonpath.
    This function translates deepdiff paths into regular jsonpath expressions.

    deepdiff paths start with "root" followed by a series of square bracket expressions
    fields and indices, e.g. `root['openshiftResources'][1]['version']`. The matching
    jsonpath expression is `openshiftResources.[1].version`
    """
    if not deep_diff_path.startswith("root"):
        raise ValueError("a deepdiff path must start with 'root'")

    def build_jsonpath_part(element: str) -> jsonpath_ng.JSONPath:
        if element.isdigit():
            return jsonpath_ng.Index(int(element))
        else:
            return jsonpath_ng.Fields(element)

    path_parts = [
        build_jsonpath_part(p) for p in DEEP_DIFF_RE.findall(deep_diff_path[4:])
    ]
    if path_parts:
        return reduce(lambda a, b: a.child(b), path_parts)
    else:
        return jsonpath_ng.Root()


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
    for c in change_type.changes or []:
        if isinstance(c, ChangeTypeChangeDetectorJsonPathProviderV1):
            change_schema = c.change_schema or change_type.context_schema
            if change_schema:
                for jsonpath_expression in c.json_path_selectors or []:
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


class Approver(Protocol):
    """
    Minimalistic protocol of an approver to be used in ChangeTypeContexts.
    Since we might load different approver contexts via GraphQL query classes,
    a protocol enables us to deal with different dataclasses representing an
    approver.
    """

    org_username: str


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


def cover_changes_with_self_service_roles(
    roles: list[RoleV1],
    change_type_processors: list[ChangeTypeProcessor],
    bundle_changes: list[BundleFileChange],
    saas_file_owner_change_type_name: Optional[str] = None,
) -> None:
    """
    Cover changes with ChangeTypeV1 associated to datafiles and resources via a
    RoleV1 saas_file_owners and self_service configuration.
    """

    # role lookup enables fast lookup roles for (filetype, filepath, changetype-name)
    role_lookup: dict[Tuple[BundleFileType, str, str], list[RoleV1]] = defaultdict(list)
    for r in roles:
        # build role lookup for owned_saas_files section of a role
        if saas_file_owner_change_type_name and r.owned_saas_files:
            for saas_file in r.owned_saas_files:
                if saas_file:
                    role_lookup[
                        (
                            BundleFileType.DATAFILE,
                            saas_file.path,
                            saas_file_owner_change_type_name,
                        )
                    ].append(r)

        # build role lookup for self_service section of a role
        if r.self_service:
            for ss in r.self_service:
                if ss and ss.datafiles:
                    for df in ss.datafiles:
                        if df:
                            role_lookup[
                                (BundleFileType.DATAFILE, df.path, ss.change_type.name)
                            ].append(r)
                if ss and ss.resources:
                    for res in ss.resources:
                        if res:
                            role_lookup[
                                (BundleFileType.RESOURCEFILE, res, ss.change_type.name)
                            ].append(r)

    # match every BundleChange with every relevant ChangeTypeV1
    for bc in bundle_changes:
        for ctp in change_type_processors:
            datafile_refs = bc.extract_context_file_refs(ctp.change_type)
            for df_ref in datafile_refs:
                # if the context file is bound with the change type in
                # a role, build a changetypecontext
                for role in role_lookup[
                    (df_ref.file_type, df_ref.path, ctp.change_type.name)
                ]:
                    bc.cover_changes(
                        ChangeTypeContext(
                            change_type_processor=ctp,
                            context=f"RoleV1 - {role.name}",
                            approvers=[u for u in role.users or [] if u],
                        )
                    )


def cover_changes(
    changes: list[BundleFileChange],
    change_type_processors: list[ChangeTypeProcessor],
    comparision_gql_api: gql.GqlApi,
    saas_file_owner_change_type_name: Optional[str] = None,
) -> None:
    """
    Coordinating function that can reach out to different `cover_*` functions
    leveraging different approver contexts.
    """

    # self service roles coverage
    roles = fetch_self_service_roles(comparision_gql_api)
    cover_changes_with_self_service_roles(
        bundle_changes=changes,
        change_type_processors=change_type_processors,
        roles=roles,
        saas_file_owner_change_type_name=saas_file_owner_change_type_name,
    )

    # ... add more cover_* functions to cover more changes based on dynamic
    # or static contexts. some ideas:
    # - users should be able to change certain things in their user file without
    #   explicit configuration in app-interface
    # - ...


def fetch_self_service_roles(gql_api: gql.GqlApi) -> list[RoleV1]:
    roles = self_service_roles.query(gql_api.query).roles or []
    return [r for r in roles if r and (r.self_service or r.owned_saas_files)]


def fetch_change_type_processors(gql_api: gql.GqlApi) -> list[ChangeTypeProcessor]:
    change_type_list = change_types.query(gql_api.query).change_types or []
    return [build_change_type_processor(ct) for ct in change_type_list if ct]


def fetch_bundle_changes(comparison_sha: str) -> list[BundleFileChange]:
    """
    reaches out to the qontract-server diff endpoint to find the files that
    changed within two bundles (the current one representing the MR and the
    explicitely passed comparision bundle - usually the state of the master branch).
    """
    changes = gql.get_diff(comparison_sha)
    return _parse_bundle_changes(changes)


def _parse_bundle_changes(bundle_changes) -> list[BundleFileChange]:
    """
    parses the output of the qontract-server /diff endpoint
    """
    change_list = [
        create_bundle_file_change(
            path=c.get("datafilepath"),
            schema=c.get("datafileschema"),
            file_type=BundleFileType.DATAFILE,
            old_file_content=c.get("old"),
            new_file_content=c.get("new"),
        )
        for c in bundle_changes["datafiles"].values()
    ]
    change_list.extend(
        [
            create_bundle_file_change(
                path=c.get("resourcepath"),
                schema=c.get("new", {}).get("$schema", c.get("old", {}).get("$schema")),
                file_type=BundleFileType.RESOURCEFILE,
                old_file_content=c.get("old", {}).get("content"),
                new_file_content=c.get("new", {}).get("content"),
            )
            for c in bundle_changes["resources"].values()
        ]
    )
    # get rid of Nones - create_bundle_file_change returns None if no real change has been detected
    return [c for c in change_list if c]


def run(
    dry_run: bool,
    comparison_sha: str,
    saas_file_owner_change_type_name: Optional[str] = None,
) -> None:
    comparision_gql_api = gql.get_api_for_sha(
        comparison_sha, QONTRACT_INTEGRATION, validate_schemas=False
    )

    # fetch change-types from current bundle to verify they are syntactically correct.
    # this is a cheap way to figure out if a newly introduced change-type works.
    # needs a lot of improvements!
    fetch_change_type_processors(gql.get_api())

    # get change types from the comparison bundle to prevent privilege escalation
    change_type_processors = fetch_change_type_processors(comparision_gql_api)

    # an error while trying to cover changes will not fail the integration
    # and the PR check - self service merges will not be available though
    try:
        changes = fetch_bundle_changes(comparison_sha)
        cover_changes(
            changes,
            change_type_processors,
            comparision_gql_api,
            saas_file_owner_change_type_name,
        )

        results = []
        for c in changes:
            for d in c.diffs:
                item = {
                    "file": c.fileref.path,
                    "schema": c.fileref.schema,
                    "changed path": d.path,
                }
                if str(d.path) != "$":
                    item.update(
                        {
                            "old value": d.old_value_repr(),
                            "new value": d.new_value_repr(),
                        }
                    )
                if d.covered_by:
                    item.update(
                        {
                            "change type": d.covered_by[
                                0
                            ].change_type_processor.change_type.name,
                            "context": d.covered_by[0].context,
                            "approvers": ", ".join(
                                [a.org_username for a in d.covered_by[0].approvers]
                            )[:20],
                        }
                    )
                results.append(item)

        print_table(
            results,
            [
                "file",
                "changed path",
                "old value",
                "new value",
                "change type",
                "context",
                "approvers",
            ],
        )

    except BaseException:
        logging.error(traceback.format_exc())
