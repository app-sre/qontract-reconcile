import copy
import itertools
import logging
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import (
    dataclass,
    field,
)
from typing import Any

import anymarkup

from reconcile.change_owners.bundle import (
    DATAFILE_PATH_FIELD_NAME,
    DATAFILE_SCHEMA_FIELD_NAME,
    BundleFileType,
    FileRef,
    QontractServerDiff,
)
from reconcile.change_owners.change_types import (
    ChangeTypeContext,
    ChangeTypePriority,
    ChangeTypeProcessor,
    DiffCoverage,
)
from reconcile.change_owners.diff import (
    Diff,
    DiffType,
    extract_diffs,
)
from reconcile.utils import gql
from reconcile.utils.jsonpath import parse_jsonpath

METADATA_CHANGE_PATH = "_metadata_"
"""
The path used to represent a metadata only change.
"""


@dataclass
class BundleFileChange:
    """
    Represents a file within an app-interface bundle that changed during an MR.
    It holds the old and new state of that file, along with precise differences
    between those states.
    """

    fileref: FileRef
    old: dict[str, Any] | None
    new: dict[str, Any] | None
    old_content_sha: str
    new_content_sha: str
    diffs: list[Diff]
    old_backrefs: set[FileRef] = field(default_factory=set)
    new_backrefs: set[FileRef] = field(default_factory=set)
    metadata_only_change: bool = False
    _diff_coverage: dict[str, DiffCoverage] = field(init=False, default_factory=dict)

    def __post_init__(self) -> None:
        self._diff_coverage = {d.path_str(): DiffCoverage(d, []) for d in self.diffs}

    def _metadata_only_diff_coverage(self) -> DiffCoverage:
        if not self.metadata_only_change:
            raise ValueError("not a metadata only change")
        if METADATA_CHANGE_PATH not in self._diff_coverage:
            # create an artificial diff coverage for metadata only changes
            # which can hold all the change type contexts that cover it
            self._diff_coverage[METADATA_CHANGE_PATH] = DiffCoverage(
                Diff(
                    path=parse_jsonpath(METADATA_CHANGE_PATH),
                    diff_type=DiffType.CHANGED,
                    old=None,
                    new=None,
                ),
                [],
            )
        return self._diff_coverage[METADATA_CHANGE_PATH]

    @property
    def old_content_with_metadata(self) -> dict[str, Any] | None:
        return self._content_with_metadata(self.old)

    @property
    def new_content_with_metadata(self) -> dict[str, Any] | None:
        return self._content_with_metadata(self.new)

    def _content_with_metadata(
        self, content: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        if content and self.fileref.file_type == BundleFileType.DATAFILE:
            content_copy = copy.deepcopy(content)
            content_copy[DATAFILE_PATH_FIELD_NAME] = self.fileref.path
            content_copy[DATAFILE_SCHEMA_FIELD_NAME] = self.fileref.schema
            return content_copy

        return content

    def is_file_deletion(self) -> bool:
        return self.old is not None and self.new is None

    def is_file_creation(self) -> bool:
        return self.old is None and self.new is not None

    def cover_changes(self, change_type_context: ChangeTypeContext) -> dict[str, Diff]:
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

        # if this is a metadata only change, register the change type context
        # as a source of approvers
        if self.metadata_only_change and not self.diffs:
            self._metadata_only_diff_coverage().coverage.append(change_type_context)
            return {}

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

        return covered_diffs

    def _cover_changes_for_diffs(
        self,
        diffs: list[DiffCoverage],
        file_content: Any,
        change_type_context: ChangeTypeContext,
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
                    elif dc.path_under_changed_path(allowed_path):
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

    @property
    def change_owner_labels(self) -> set[str]:
        """
        returns the set of change owner labels that are attached to the
        BundleFileChanges DiffCoverage
        """
        labels = set()
        for dc in self.diff_coverage:
            labels.update(dc.change_owner_labels)
        return labels

    def involved_change_types(self) -> list[ChangeTypeProcessor]:
        """
        returns all the change-types that are involved in the coverage
        of all changes
        """
        change_types = []
        for dc in self.diff_coverage:
            for ctx in dc.coverage:
                change_types.append(ctx.change_type_processor)
        return change_types


def parse_resource_file_content(content: Any | None) -> tuple[Any, str | None]:
    if content:
        try:
            data = anymarkup.parse(content, force_types=None)
            return data, data.get("$schema")
        except Exception:
            # not parsable content - we will just deal with the plain content
            return content, None
    else:
        return None, None


def _create_bundle_file_change(
    path: str,
    schema: str | None,
    file_type: BundleFileType,
    old_file_content: Any,
    new_file_content: Any,
    old_content_sha: str,
    new_content_sha: str,
    old_path: str,
    new_path: str,
    old_backrefs: list[FileRef] | None = None,
    new_backrefs: list[FileRef] | None = None,
) -> BundleFileChange | None:
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
            old_content_sha=old_content_sha,
            new_content_sha=new_content_sha,
            old_backrefs=set(old_backrefs or []),
            new_backrefs=set(new_backrefs or []),
            diffs=diffs,
        )

    if old_content_sha != new_content_sha or old_path != new_path:
        # there were no diffs but the content of the file has changed, e.g.
        # - the SHA of the file: the SHA can change even when no diffs are detected.
        #   this can be happen in case something undetectable has changed, e.g. comments
        #   in a YAML file are invisible to YAML parsers
        # - item reordering in lists: we ignore change or order for list items for now,
        #   but also in this cases the SHA changes without any reported diffs
        # - the path of a file has changed a.k.a. the file was moved. in such a case
        #   the content of the file is the same but the path is different.
        # in these scenarios we will still create a BundleFileChange object, but
        # with without diffs. instead we mark it as an metadata only change.
        return BundleFileChange(
            fileref=fileref,
            old=old_file_content,
            new=new_file_content,
            old_content_sha=old_content_sha,
            new_content_sha=new_content_sha,
            old_backrefs=set(old_backrefs or []),
            new_backrefs=set(new_backrefs or []),
            metadata_only_change=True,
            diffs=[],
        )

    # no diffs and no change in metadata
    return None


def get_priority_for_changes(
    bundle_file_changes: list[BundleFileChange],
) -> ChangeTypePriority | None:
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


def fetch_bundle_changes(comparison_sha: str) -> list[BundleFileChange]:
    """
    reaches out to the qontract-server diff endpoint to find the files that
    changed within two bundles (the current one representing the MR and the
    explicitely passed comparision bundle - usually the state of the master branch).
    """
    qontract_server_diff = QontractServerDiff(**gql.get_diff(comparison_sha))
    bundle_changes = parse_bundle_changes(qontract_server_diff)

    # post process bundle changes to aggregate delete/create pairs into pure
    # metadata change
    return aggregate_file_moves(bundle_changes)


@dataclass
class _MoveCandidates:
    creations: list[BundleFileChange] = field(default_factory=list)
    deletions: list[BundleFileChange] = field(default_factory=list)

    def changes(self) -> list[BundleFileChange]:
        if len(self.creations) == 1 and len(self.deletions) == 1:
            creation = self.creations[0]
            deletion = self.deletions[0]
            if (
                deletion.fileref.file_type == creation.fileref.file_type
                and deletion.fileref.path != creation.fileref.path
            ):
                move_change = _create_bundle_file_change(
                    path=deletion.fileref.path,
                    schema=deletion.fileref.schema,
                    file_type=deletion.fileref.file_type,
                    new_file_content=deletion.old,
                    old_file_content=creation.new,
                    old_content_sha=deletion.old_content_sha,
                    new_content_sha=creation.new_content_sha,
                    old_path=deletion.fileref.path,
                    new_path=creation.fileref.path,
                )
                if move_change:
                    # make mypy happy
                    return [move_change]

        # the candidates turned out to be not a file move, so we
        # will use the original changes as is
        return self.creations + self.deletions


def aggregate_file_moves(
    bundle_changes: list[BundleFileChange],
) -> list[BundleFileChange]:
    """
    This function tries to detect file moves by looking at the bundle changes. If an
    add and remove file change with the same content is detected, those changes are
    replaced with a single move change where the only difference is the path.
    """
    move_candidates: dict[str, _MoveCandidates] = defaultdict(_MoveCandidates)
    new_bundle_changes = []
    for c in bundle_changes:
        if c.is_file_creation():
            move_candidates[c.new_content_sha].creations.append(c)
        elif c.is_file_deletion():
            move_candidates[c.old_content_sha].deletions.append(c)
        else:
            new_bundle_changes.append(c)
    move_candidate_changes = itertools.chain.from_iterable(
        c.changes() for c in move_candidates.values()
    )
    new_bundle_changes.extend(move_candidate_changes)
    return new_bundle_changes


def parse_bundle_changes(
    qontract_server_diff: QontractServerDiff,
) -> list[BundleFileChange]:
    """
    parses the output of the qontract-server /diff endpoint
    """
    logging.debug(
        f"bundle contains {len(qontract_server_diff.datafiles)} changed datafiles and {len(qontract_server_diff.resources)} changed resourcefiles"
    )

    change_list = []
    for df in qontract_server_diff.datafiles.values():
        bc = _create_bundle_file_change(
            path=df.datafilepath,
            schema=df.datafileschema,
            file_type=BundleFileType.DATAFILE,
            old_file_content=df.cleaned_old_data,
            new_file_content=df.cleaned_new_data,
            old_content_sha=df.old_data_sha or "",
            new_content_sha=df.new_data_sha or "",
            old_path=df.old_datafilepath or "",
            new_path=df.new_datafilepath or "",
        )
        if bc is not None:
            change_list.append(bc)
        else:
            logging.debug(f"skipping datafile {df.datafilepath} - no changes detected")

    for rf in qontract_server_diff.resources.values():
        bc = _create_bundle_file_change(
            path=rf.resourcepath,
            schema=rf.resourcefileschema,
            file_type=BundleFileType.RESOURCEFILE,
            old_file_content=rf.old.content if rf.old else None,
            new_file_content=rf.new.content if rf.new else None,
            old_content_sha=rf.old.sha256sum if rf.old else "",
            new_content_sha=rf.new.sha256sum if rf.new else "",
            old_path=rf.old.path if rf.old else "",
            new_path=rf.new.path if rf.new else "",
            old_backrefs=[
                FileRef(
                    file_type=BundleFileType.DATAFILE,
                    path=br.path,
                    schema=br.datafileschema,
                    json_path=br.jsonpath,
                )
                for br in (rf.old.backrefs if rf.old and rf.old.backrefs else [])
            ],
            new_backrefs=[
                FileRef(
                    file_type=BundleFileType.DATAFILE,
                    path=br.path,
                    schema=br.datafileschema,
                    json_path=br.jsonpath,
                )
                for br in (rf.new.backrefs if rf.new and rf.new.backrefs else [])
            ],
        )
        if bc is not None:
            change_list.append(bc)
        else:
            logging.debug(
                f"skipping resourcefile {rf.resourcepath} - no changes detected"
            )

    return change_list


def aggregate_resource_changes(
    bundle_changes: list[BundleFileChange],
    content_store: dict[str, Any],
    supported_schemas: set[str],
) -> list[BundleFileChange]:
    resource_changes = [
        BundleFileChange(
            fileref=file_ref,
            old=file_content,
            new=file_content,
            old_content_sha="",
            new_content_sha="",
            diffs=[
                Diff(
                    path=parse_jsonpath(file_ref.json_path),
                    diff_type=DiffType.CHANGED,
                    old=file_content,
                    new=file_content,
                )
            ],
        )
        for change in bundle_changes
        for file_ref in change.old_backrefs | change.new_backrefs
        if file_ref.schema in supported_schemas
        and (file_content := content_store[file_ref.path])
    ]

    return bundle_changes + resource_changes
