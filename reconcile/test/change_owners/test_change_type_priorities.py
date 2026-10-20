from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest

from reconcile.change_owners.approver import Approver
from reconcile.change_owners.change_types import (
    ChangeTypeContext,
    ChangeTypePriority,
)
from reconcile.change_owners.changes import (
    BundleFileChange,
    get_priority_for_changes,
)
from reconcile.test.change_owners.fixtures import (
    StubFile,
    build_change_type,
    change_type_to_processor,
)

if TYPE_CHECKING:
    from reconcile.gql_definitions.change_owners.queries.change_types import (
        ChangeTypeV1,
    )

#
# priority tests
#


def test_priority_for_changes(
    saas_file_changetype: ChangeTypeV1, secret_promoter_change_type: ChangeTypeV1
) -> None:
    saas_file_changetype.priority = ChangeTypePriority.HIGH.value
    secret_promoter_change_type.priority = ChangeTypePriority.MEDIUM.value
    c1 = BundleFileChange(
        fileref=None,  # type: ignore
        old=None,
        new=None,
        old_content_sha="",
        new_content_sha="",
        diffs=[],
    )
    c1.diff_priorities = MagicMock(  # type: ignore
        return_value=[change_type_to_processor(saas_file_changetype).priority]
    )
    c2 = BundleFileChange(
        fileref=None,  # type: ignore
        old=None,
        new=None,
        old_content_sha="",
        new_content_sha="",
        diffs=[],
    )
    c2.diff_priorities = MagicMock(  # type: ignore
        return_value=[change_type_to_processor(secret_promoter_change_type).priority]
    )

    assert get_priority_for_changes([c1, c2]) == ChangeTypePriority.MEDIUM


def test_priorty_for_changes_no_coverage() -> None:
    changes = [
        BundleFileChange(
            fileref=None,  # type: ignore
            old=None,
            new=None,
            old_content_sha="",
            new_content_sha="",
            diffs=[],
        )
    ]
    assert get_priority_for_changes(changes) is None


def test_priority_for_changes_same_diff_covered_by_multiple_priorities(
    saas_file_changetype: ChangeTypeV1, saas_file: StubFile
) -> None:
    """
    Mirrors app-interface MRs !173788 and !213791: a single literal change
    can be matched by more than one change-type at once -- e.g. a narrow,
    high-priority change-type (like a dedicated hotfix-field change-type)
    and a broad, low-priority umbrella change-type (like app-owner's
    catch-all selector) that happens to also cover the same field. That
    diff's priority must resolve to the more permissive (highest) of the
    two, not silently collapse to the lowest as a naive "lowest priority
    wins across the whole MR" reduction would do.

    A second, genuinely low-only diff elsewhere in the same MR still caps
    the MR's overall priority -- the conservative floor across *distinct*
    diffs is unchanged.
    """
    saas_file_changetype.priority = ChangeTypePriority.URGENT.value
    narrow_urgent_ctx = ChangeTypeContext(
        change_type_processor=change_type_to_processor(saas_file_changetype),
        context="RoleV1 - urgent-approver",
        origin="",
        approvers=[Approver(org_username="user", tag_on_merge_requests=False)],
        context_file=saas_file.file_ref(),
    )

    broad_low_priority_changetype = saas_file_changetype.model_copy(deep=True)
    broad_low_priority_changetype.name = "saas-file-umbrella"
    broad_low_priority_changetype.priority = ChangeTypePriority.LOW.value
    broad_low_priority_changetype.changes[0].json_path_selectors = [  # type: ignore
        "resourceTemplates"
    ]
    broad_low_ctx = ChangeTypeContext(
        change_type_processor=change_type_to_processor(broad_low_priority_changetype),
        context="RoleV1 - low-approver",
        origin="",
        approvers=[Approver(org_username="user", tag_on_merge_requests=False)],
        context_file=saas_file.file_ref(),
    )

    # `resourceTemplates[0].targets[0].ref` is covered by both the narrow
    # urgent change-type and the broad low-priority umbrella change-type.
    # `resourceTemplates[0].name` is covered only by the broad umbrella one.
    change = saas_file.create_bundle_change({
        "resourceTemplates[0].targets[0].ref": "new-ref",
        "resourceTemplates[0].name": "new-name",
    })
    change.cover_changes(narrow_urgent_ctx)
    change.cover_changes(broad_low_ctx)

    assert set(change.diff_priorities()) == {
        ChangeTypePriority.URGENT,
        ChangeTypePriority.LOW,
    }
    # the unrelated, low-only `name` change still caps the whole MR
    assert get_priority_for_changes([change]) == ChangeTypePriority.LOW

    # once the MR only touches the field covered by both change-types (the
    # actual shape of !173788 / !213791), the redundant low-priority grant
    # no longer suppresses the urgent one
    hotfix_only_change = saas_file.create_bundle_change({
        "resourceTemplates[0].targets[0].ref": "new-ref",
    })
    hotfix_only_change.cover_changes(narrow_urgent_ctx)
    hotfix_only_change.cover_changes(broad_low_ctx)

    assert get_priority_for_changes([hotfix_only_change]) == ChangeTypePriority.URGENT


@pytest.mark.parametrize("cover_order", ["broad_then_narrow", "narrow_then_broad"])
def test_priority_for_changes_ancestor_coverage_is_order_independent(
    saas_file_changetype: ChangeTypeV1, saas_file: StubFile, cover_order: str
) -> None:
    """
    Regression test for an ordering bug in ancestor-coverage resolution:
    `cover_changes()` appends an ancestor-level selector's context directly
    onto the (potentially already split) parent `DiffCoverage.coverage` --
    it does not retroactively propagate into a split created earlier for a
    narrower, nested selector (only `add_covering_context`, used for splits
    created *after* the fact, does that). So a diff split's own `coverage`
    list can be missing ancestor grants recorded before the split existed,
    and `diff_priorities()` must walk up `DiffCoverage.parent` to find them
    rather than relying on each `cover_changes()` call happening in a
    particular order.

    Adding `parameters.NEW = {"a": 1}` with an urgent selector on the
    ancestor `parameters` and a low selector on the descendant
    `parameters.NEW.a` must resolve to urgent regardless of which
    change-type is processed first.
    """
    saas_file_changetype.priority = ChangeTypePriority.URGENT.value
    saas_file_changetype.changes[0].json_path_selectors = ["parameters"]  # type: ignore
    broad_ctx = ChangeTypeContext(
        change_type_processor=change_type_to_processor(saas_file_changetype),
        context="RoleV1 - broad-approver",
        origin="",
        approvers=[Approver(org_username="user", tag_on_merge_requests=False)],
        context_file=saas_file.file_ref(),
    )

    narrow_low_priority_changetype = saas_file_changetype.model_copy(deep=True)
    narrow_low_priority_changetype.name = "parameters-new-a-only"
    narrow_low_priority_changetype.priority = ChangeTypePriority.LOW.value
    narrow_low_priority_changetype.changes[0].json_path_selectors = [  # type: ignore
        "parameters.NEW.a"
    ]
    narrow_ctx = ChangeTypeContext(
        change_type_processor=change_type_to_processor(narrow_low_priority_changetype),
        context="RoleV1 - narrow-approver",
        origin="",
        approvers=[Approver(org_username="user", tag_on_merge_requests=False)],
        context_file=saas_file.file_ref(),
    )

    new_content = copy.deepcopy(saas_file.content)
    new_content["parameters"]["NEW"] = {"a": 1}
    change = saas_file.create_bundle_change_with_new_content(new_content)

    if cover_order == "broad_then_narrow":
        change.cover_changes(broad_ctx)
        change.cover_changes(narrow_ctx)
    else:
        change.cover_changes(narrow_ctx)
        change.cover_changes(broad_ctx)

    assert get_priority_for_changes([change]) == ChangeTypePriority.URGENT


@pytest.mark.parametrize("cover_order", ["broad_then_narrow", "narrow_then_broad"])
def test_priority_for_changes_redundant_parent_does_not_cap_fully_split_child(
    saas_file_changetype: ChangeTypeV1, saas_file: StubFile, cover_order: str
) -> None:
    """
    Regression test: `DiffCoverage.fine_grained_diff_coverages` returns a
    directly-covered parent alongside its splits even when those splits
    between them account for all of the parent's changed content -- it only
    drops a parent that has *no* direct coverage of its own. Such a parent
    is not separate, disjoint content; it is the same content its splits
    already represent, more precisely. Counting the parent's own priority
    as if it were additional content let a redundant low-priority grant cap
    an otherwise fully-urgent diff, independent of call order.

    Adding `parameters.NEW = {"a": 1}` with a LOW selector on the ancestor
    `parameters` and an URGENT selector on the descendant `parameters.NEW.a`
    -- which between them fully cover `parameters.NEW`'s only key -- must
    resolve to urgent, not low, regardless of order.
    """
    saas_file_changetype.priority = ChangeTypePriority.LOW.value
    saas_file_changetype.changes[0].json_path_selectors = ["parameters"]  # type: ignore
    broad_low_ctx = ChangeTypeContext(
        change_type_processor=change_type_to_processor(saas_file_changetype),
        context="RoleV1 - broad-low-approver",
        origin="",
        approvers=[Approver(org_username="user", tag_on_merge_requests=False)],
        context_file=saas_file.file_ref(),
    )

    narrow_urgent_changetype = saas_file_changetype.model_copy(deep=True)
    narrow_urgent_changetype.name = "parameters-new-a-only"
    narrow_urgent_changetype.priority = ChangeTypePriority.URGENT.value
    narrow_urgent_changetype.changes[0].json_path_selectors = [  # type: ignore
        "parameters.NEW.a"
    ]
    narrow_urgent_ctx = ChangeTypeContext(
        change_type_processor=change_type_to_processor(narrow_urgent_changetype),
        context="RoleV1 - narrow-urgent-approver",
        origin="",
        approvers=[Approver(org_username="user", tag_on_merge_requests=False)],
        context_file=saas_file.file_ref(),
    )

    new_content = copy.deepcopy(saas_file.content)
    new_content["parameters"]["NEW"] = {"a": 1}
    change = saas_file.create_bundle_change_with_new_content(new_content)

    if cover_order == "broad_then_narrow":
        change.cover_changes(broad_low_ctx)
        change.cover_changes(narrow_urgent_ctx)
    else:
        change.cover_changes(narrow_urgent_ctx)
        change.cover_changes(broad_low_ctx)

    assert get_priority_for_changes([change]) == ChangeTypePriority.URGENT


def test_priority_for_changes_partially_split_parent_still_caps_uncovered_content(
    saas_file_changetype: ChangeTypeV1, saas_file: StubFile
) -> None:
    """
    Companion to the redundant-parent regression test above: when a split
    only accounts for *part* of its parent's changed content, the parent's
    own priority must still apply to the part none of its splits cover --
    that portion is genuinely disjoint, lower-priority-only content, not a
    redundant restatement of what a split already covers.

    `parameters.NEW = {"a": 1, "b": 2}` with a LOW selector on `parameters`
    and an URGENT selector on only `parameters.NEW.a` leaves `b` covered
    solely by the low-priority grant, so the MR as a whole stays low.
    """
    saas_file_changetype.priority = ChangeTypePriority.LOW.value
    saas_file_changetype.changes[0].json_path_selectors = ["parameters"]  # type: ignore
    broad_low_ctx = ChangeTypeContext(
        change_type_processor=change_type_to_processor(saas_file_changetype),
        context="RoleV1 - broad-low-approver",
        origin="",
        approvers=[Approver(org_username="user", tag_on_merge_requests=False)],
        context_file=saas_file.file_ref(),
    )

    narrow_urgent_changetype = saas_file_changetype.model_copy(deep=True)
    narrow_urgent_changetype.name = "parameters-new-a-only"
    narrow_urgent_changetype.priority = ChangeTypePriority.URGENT.value
    narrow_urgent_changetype.changes[0].json_path_selectors = [  # type: ignore
        "parameters.NEW.a"
    ]
    narrow_urgent_ctx = ChangeTypeContext(
        change_type_processor=change_type_to_processor(narrow_urgent_changetype),
        context="RoleV1 - narrow-urgent-approver",
        origin="",
        approvers=[Approver(org_username="user", tag_on_merge_requests=False)],
        context_file=saas_file.file_ref(),
    )

    new_content = copy.deepcopy(saas_file.content)
    new_content["parameters"]["NEW"] = {"a": 1, "b": 2}
    change = saas_file.create_bundle_change_with_new_content(new_content)
    change.cover_changes(broad_low_ctx)
    change.cover_changes(narrow_urgent_ctx)

    assert set(change.diff_priorities()) == {
        ChangeTypePriority.URGENT,
        ChangeTypePriority.LOW,
    }
    assert get_priority_for_changes([change]) == ChangeTypePriority.LOW


def _empty_object_old_and_new_content(
    saas_file: StubFile, diff_type: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Returns (old_content, new_content) with an empty `parameters.NEW: {}`
    either added (old -> new) or removed (new -> old), as a plain content
    pair so callers can layer further changes onto `new_content` as needed.
    """
    content = copy.deepcopy(saas_file.content)
    empty_object_content = copy.deepcopy(saas_file.content)
    empty_object_content["parameters"]["NEW"] = {}
    if diff_type == "added":
        return content, empty_object_content
    return empty_object_content, content


def _bundle_change(
    saas_file: StubFile, old_content: dict[str, Any], new_content: dict[str, Any]
) -> BundleFileChange:
    old_stub = StubFile(
        filepath=saas_file.filepath,
        fileschema=saas_file.fileschema,
        filetype=saas_file.filetype,
        content=old_content,
    )
    return old_stub.create_bundle_change_with_new_content(new_content)


@pytest.mark.parametrize("diff_type", ["added", "removed"])
def test_priority_for_changes_empty_object_diff_keeps_its_own_priority(
    saas_file_changetype: ChangeTypeV1, saas_file: StubFile, diff_type: str
) -> None:
    """
    Regression test: `is_covered_by_splits()` treats an empty dict as
    vacuously "nothing left uncovered" -- `{}` is falsy, so its "is there
    any uncovered data remaining" check short-circuits to `True` before
    ever looking at `diff_fragments`, even when there are no splits at all.
    Combined with the redundant-parent skip above, a directly covered
    empty-object diff (e.g. adding or removing `parameters.NEW: {}`) was
    wrongly treated as fully redundant and dropped from `diff_priorities()`
    even though nothing actually covers it except its own direct grant.

    With only that diff in the MR, this used to silently produce no
    priority at all (`get_priority_for_changes` returning `None` despite
    the diff being covered and approvable).
    """
    saas_file_changetype.priority = ChangeTypePriority.LOW.value
    saas_file_changetype.changes[0].json_path_selectors = ["parameters"]  # type: ignore
    low_ctx = ChangeTypeContext(
        change_type_processor=change_type_to_processor(saas_file_changetype),
        context="RoleV1 - low-approver",
        origin="",
        approvers=[Approver(org_username="user", tag_on_merge_requests=False)],
        context_file=saas_file.file_ref(),
    )

    old_content, new_content = _empty_object_old_and_new_content(saas_file, diff_type)
    change = _bundle_change(saas_file, old_content, new_content)
    change.cover_changes(low_ctx)

    assert change.diff_priorities() == [ChangeTypePriority.LOW]
    assert get_priority_for_changes([change]) == ChangeTypePriority.LOW


@pytest.mark.parametrize("diff_type", ["added", "removed"])
def test_priority_for_changes_empty_object_diff_does_not_inflate_to_unrelated_urgent(
    saas_file_changetype: ChangeTypeV1, saas_file: StubFile, diff_type: str
) -> None:
    """
    Companion to the test above: when a dropped empty-object diff's `LOW`
    priority silently disappears from `diff_priorities()`, an unrelated
    diff covered at `urgent` elsewhere in the same MR is left as the only
    entry, so the MR incorrectly resolves to `urgent` instead of `low`.
    """
    saas_file_changetype.priority = ChangeTypePriority.LOW.value
    saas_file_changetype.changes[0].json_path_selectors = ["parameters"]  # type: ignore
    low_ctx = ChangeTypeContext(
        change_type_processor=change_type_to_processor(saas_file_changetype),
        context="RoleV1 - low-approver",
        origin="",
        approvers=[Approver(org_username="user", tag_on_merge_requests=False)],
        context_file=saas_file.file_ref(),
    )

    unrelated_urgent_changetype = saas_file_changetype.model_copy(deep=True)
    unrelated_urgent_changetype.name = "unrelated-urgent"
    unrelated_urgent_changetype.priority = ChangeTypePriority.URGENT.value
    unrelated_urgent_changetype.changes[0].json_path_selectors = [  # type: ignore
        "resourceTemplates[*].targets[*].ref"
    ]
    urgent_ctx = ChangeTypeContext(
        change_type_processor=change_type_to_processor(unrelated_urgent_changetype),
        context="RoleV1 - urgent-approver",
        origin="",
        approvers=[Approver(org_username="user", tag_on_merge_requests=False)],
        context_file=saas_file.file_ref(),
    )

    old_content, new_content = _empty_object_old_and_new_content(saas_file, diff_type)
    new_content["resourceTemplates"][0]["targets"][0]["ref"] = "new-ref"
    change = _bundle_change(saas_file, old_content, new_content)
    change.cover_changes(low_ctx)
    change.cover_changes(urgent_ctx)

    assert set(change.diff_priorities()) == {
        ChangeTypePriority.LOW,
        ChangeTypePriority.URGENT,
    }
    assert get_priority_for_changes([change]) == ChangeTypePriority.LOW


def _priority_context(
    saas_file: StubFile,
    selector: str,
    priority: ChangeTypePriority,
    *,
    disabled: bool = False,
) -> ChangeTypeContext:
    processor = build_change_type(selector, [selector])
    processor.priority = priority
    processor.disabled = disabled
    return ChangeTypeContext(
        change_type_processor=processor,
        context=selector,
        origin="",
        approvers=[Approver(org_username="user", tag_on_merge_requests=False)],
        context_file=saas_file.file_ref(),
    )


@pytest.mark.parametrize("diff_type", ["added", "removed"])
@pytest.mark.parametrize("narrow_first", [False, True])
@pytest.mark.parametrize(
    ("value", "selector", "expected_priorities"),
    [
        ([1, 2], "parameters.NEW[*]", {ChangeTypePriority.URGENT}),
        (list(range(12)), "parameters.NEW[*]", {ChangeTypePriority.URGENT}),
        (
            [1, 2],
            "parameters.NEW[0]",
            {ChangeTypePriority.LOW, ChangeTypePriority.URGENT},
        ),
        (
            [{"ref": "one"}, {"ref": "two"}],
            "parameters.NEW[*].ref",
            {ChangeTypePriority.URGENT},
        ),
        (
            [{"ref": "one", "extra": {}}],
            "parameters.NEW[*].ref",
            {ChangeTypePriority.LOW, ChangeTypePriority.URGENT},
        ),
        (
            [[1, 2], [3]],
            "parameters.NEW[*][*]",
            {ChangeTypePriority.URGENT},
        ),
    ],
)
def test_priority_for_changes_list_splits(
    saas_file: StubFile,
    diff_type: str,
    narrow_first: bool,
    value: list[Any],
    selector: str,
    expected_priorities: set[ChangeTypePriority],
) -> None:
    old_content = copy.deepcopy(saas_file.content)
    new_content = copy.deepcopy(saas_file.content)
    new_content["parameters"]["NEW"] = value
    if diff_type == "removed":
        old_content, new_content = new_content, old_content
    change = _bundle_change(saas_file, old_content, new_content)
    contexts = [
        _priority_context(saas_file, "parameters", ChangeTypePriority.LOW),
        _priority_context(saas_file, selector, ChangeTypePriority.URGENT),
    ]
    for ctx in reversed(contexts) if narrow_first else contexts:
        change.cover_changes(ctx)

    original_content = copy.deepcopy((change.old, change.new))
    assert set(change.diff_priorities()) == expected_priorities
    assert get_priority_for_changes([change]) == (
        ChangeTypePriority.LOW
        if ChangeTypePriority.LOW in expected_priorities
        else ChangeTypePriority.URGENT
    )
    assert (change.old, change.new) == original_content


@pytest.mark.parametrize("diff_type", ["added", "removed"])
@pytest.mark.parametrize("narrow_first", [False, True])
@pytest.mark.parametrize("empty_value", [{}, []])
@pytest.mark.parametrize("unrelated_urgent", [False, True])
def test_priority_for_changes_disabled_empty_split_keeps_parent_priority(
    saas_file: StubFile,
    diff_type: str,
    narrow_first: bool,
    empty_value: dict[str, Any] | list[Any],
    unrelated_urgent: bool,
) -> None:
    old_content = copy.deepcopy(saas_file.content)
    new_content = copy.deepcopy(saas_file.content)
    new_content["parameters"]["NEW"] = {"a": empty_value}
    if diff_type == "removed":
        old_content, new_content = new_content, old_content
    if unrelated_urgent:
        new_content["resourceTemplates"][0]["targets"][0]["ref"] = "new-ref"
    change = _bundle_change(saas_file, old_content, new_content)
    contexts = [
        _priority_context(saas_file, "parameters", ChangeTypePriority.LOW),
        _priority_context(
            saas_file,
            "parameters.NEW.a",
            ChangeTypePriority.URGENT,
            disabled=True,
        ),
    ]
    for ctx in reversed(contexts) if narrow_first else contexts:
        change.cover_changes(ctx)
    change.cover_changes(
        _priority_context(
            saas_file,
            "resourceTemplates[*].targets[*].ref",
            ChangeTypePriority.URGENT,
        )
    )

    expected_priorities = {ChangeTypePriority.LOW}
    if unrelated_urgent:
        expected_priorities.add(ChangeTypePriority.URGENT)
    assert set(change.diff_priorities()) == expected_priorities
    assert get_priority_for_changes([change]) == ChangeTypePriority.LOW
