import itertools
import logging
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import (
    dataclass,
    field,
)
from typing import (
    Any,
    Optional,
)

import anymarkup

from reconcile.change_owners.bundle import (
    BundleFileType,
    FileRef,
)
from reconcile.change_owners.change_types import (
    ChangeTypeContext,
    ChangeTypePriority,
    ChangeTypeProcessor,
    DiffCoverage,
)
from reconcile.change_owners.diff import (
    SHA256SUM_FIELD_NAME,
    SHA256SUM_PATH,
    Diff,
    DiffType,
    extract_diffs,
)
from reconcile.utils import gql


class InvalidBundleFileMetadataError(Exception):
    """
    Raised when invalid or missing metadata in a bundle file is detected.
    """


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

    def old_content_sha(self) -> str:
        """
        Returns the SHA256SUM of the old state of the file. The checksum is provided by the
        qontract-server and is not calculated locally. If the file has no old content
        (a.k.a. is currently created), this function returns an empty string. It is the responsibility
        of the caller to check if the file is created or not, e.g. via `is_file_creation()`.
        """
        if self.old is None:
            return ""
        if SHA256SUM_FIELD_NAME not in self.old:
            raise InvalidBundleFileMetadataError(
                f"The detected change for {self.fileref} does not contain a {SHA256SUM_FIELD_NAME} for the previous state."
            )
        return self.old[SHA256SUM_FIELD_NAME]

    def new_content_sha(self) -> str:
        """
        Returns the SHA256SUM of the new state of the file. The checksum is provided by the
        qontract-server and is not calculated locally. If the file has no new content
        (a.k.a. is currently deleted), this function returns an empty string. It is the responsibility
        of the caller to check if the file is deleted or not, e.g. via `is_file_deletion()`.
        """
        if self.new is None:
            return ""
        if SHA256SUM_FIELD_NAME not in self.new:
            raise InvalidBundleFileMetadataError(
                f"The detected change for {self.fileref} does not contain a {SHA256SUM_FIELD_NAME} for the new state."
            )
        return self.new[SHA256SUM_FIELD_NAME]

    def is_file_deletion(self) -> bool:
        return self.old is not None and self.new is None

    def is_file_creation(self) -> bool:
        return self.old is None and self.new is not None

    def cover_changes(self, change_type_context: ChangeTypeContext) -> list[Diff]:
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
    return None


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


def fetch_bundle_changes(comparison_sha: str) -> list[BundleFileChange]:
    """
    reaches out to the qontract-server diff endpoint to find the files that
    changed within two bundles (the current one representing the MR and the
    explicitely passed comparision bundle - usually the state of the master branch).
    """
    changes = gql.get_diff(comparison_sha)
    return _parse_bundle_changes(changes)


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
                move_change = create_bundle_file_change(
                    deletion.fileref.path,
                    deletion.fileref.schema,
                    deletion.fileref.file_type,
                    deletion.old,
                    creation.new,
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
            move_candidates[c.new_content_sha()].creations.append(c)
        elif c.is_file_deletion():
            move_candidates[c.old_content_sha()].deletions.append(c)
        else:
            new_bundle_changes.append(c)
    move_candidate_changes = itertools.chain.from_iterable(
        c.changes() for c in move_candidates.values()
    )
    new_bundle_changes.extend(move_candidate_changes)
    return new_bundle_changes


def _parse_bundle_changes(bundle_changes: Any) -> list[BundleFileChange]:
    """
    parses the output of the qontract-server /diff endpoint
    """
    datafiles = bundle_changes["datafiles"].values()
    resourcefiles = bundle_changes["resources"].values()
    logging.debug(
        f"bundle contains {len(datafiles)} changed datafiles and {len(resourcefiles)} changed resourcefiles"
    )

    change_list = []
    for c in datafiles:
        bc = create_bundle_file_change(
            path=c.get("datafilepath"),
            schema=c.get("datafileschema"),
            file_type=BundleFileType.DATAFILE,
            old_file_content=c.get("old"),
            new_file_content=c.get("new"),
        )
        if bc is not None:
            change_list.append(bc)
        else:
            logging.debug(
                f"skipping datafile {c.get('datafilepath')} - no changes detected"
            )

    for c in resourcefiles:
        bc = create_bundle_file_change(
            path=c.get("resourcepath"),
            schema=c.get("new", {}).get("$schema", c.get("old", {}).get("$schema")),
            file_type=BundleFileType.RESOURCEFILE,
            old_file_content=c.get("old", {}).get("content"),
            new_file_content=c.get("new", {}).get("content"),
        )
        if bc is not None:
            change_list.append(bc)
        else:
            logging.debug(
                f"skipping resourcefile {c.get('resourcepath')} - no changes detected"
            )

    return change_list
