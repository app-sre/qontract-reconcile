from itertools import starmap

import pytest

from reconcile.change_owners.bundle import BundleFileType, FileRef
from reconcile.change_owners.change_owners import (
    build_status_message,
    is_app_sre_self_serviceable,
)
from reconcile.change_owners.change_types import (
    ChangeTypeContext,
    ChangeTypePriority,
    ChangeTypeProcessor,
)
from reconcile.change_owners.decision import ChangeDecision
from reconcile.change_owners.diff import Diff, DiffType
from reconcile.utils.jsonpath import parse_jsonpath


def build_change_decision(
    self_service_role_name: str | None, disabled: bool = False
) -> ChangeDecision:
    file_ref = FileRef(
        file_type=BundleFileType.DATAFILE,
        path="datafile.yaml",
        schema="schema.yaml",
    )
    coverage: list[ChangeTypeContext] = []
    if self_service_role_name:
        coverage.append(
            ChangeTypeContext(
                change_type_processor=ChangeTypeProcessor(
                    name="test",
                    labels=None,
                    description="",
                    priority=ChangeTypePriority.LOW,
                    context_type=BundleFileType.DATAFILE,
                    context_schema=None,
                    disabled=disabled,
                    implicit_ownership=[],
                ),
                context=f"RoleV1 - {self_service_role_name}",
                origin="change-type",
                context_file=file_ref,
                approvers=[],
                self_service_role_name=self_service_role_name,
            )
        )
    return ChangeDecision(
        file=file_ref,
        diff=Diff(
            path=parse_jsonpath("$"),
            diff_type=DiffType.CHANGED,
            old=None,
            new=None,
        ),
        coverage=coverage,
    )


@pytest.mark.parametrize(
    (
        "self_serviceable",
        "role_contexts",
        "authoritative",
        "expected_heading",
        "expect_review_queue_guidance",
        "expect_code_warning",
    ),
    [
        pytest.param(
            True,
            [("app-sre", False)],
            False,
            "## ✅ Ready for Review",
            True,
            True,
            id="app-sre-self-service",
        ),
        pytest.param(
            True,
            [("another-role", False)],
            True,
            "## ✅ Ready for Review",
            False,
            False,
            id="other-role-self-service",
        ),
        pytest.param(
            False,
            [(None, False)],
            True,
            "## 🔍 AppSRE Review Required",
            True,
            False,
            id="non-self-service",
        ),
        pytest.param(
            True,
            [("app-sre", True), ("another-role", False)],
            True,
            "## ✅ Ready for Review",
            False,
            False,
            id="disabled-app-sre-with-active-other-role",
        ),
    ],
)
def test_status_message_for_self_service_roles(
    self_serviceable: bool,
    role_contexts: list[tuple[str | None, bool]],
    authoritative: bool,
    expected_heading: str,
    expect_review_queue_guidance: bool,
    expect_code_warning: bool,
) -> None:
    change_decisions = list(starmap(build_change_decision, role_contexts))
    app_sre_self_serviceable = is_app_sre_self_serviceable(
        self_serviceable=self_serviceable,
        change_decisions=change_decisions,
    )

    message = build_status_message(
        self_serviceable=self_serviceable,
        authoritative=authoritative,
        change_admitted=True,
        approver_reachability=set(),
        supported_commands=["/lgtm"],
        app_sre_self_serviceable=app_sre_self_serviceable,
    )

    assert expected_heading in message
    assert ("review queue" in message) is expect_review_queue_guidance
    assert (
        "Code changes outside of data and resources detected" in message
    ) is expect_code_warning
    assert "**Available commands:** `/lgtm`" in message

    if self_serviceable:
        assert "Get `/lgtm` approval from the listed approvers below." in message

    if expect_review_queue_guidance:
        assert "Please don't ping directly unless this is **urgent**" in message
        assert "etiquette guide" in message

    if app_sre_self_serviceable:
        existing_review_message = build_status_message(
            self_serviceable=False,
            authoritative=authoritative,
            change_admitted=True,
            approver_reachability=set(),
            supported_commands=["/lgtm"],
        )
        reused_review_message = message.replace(
            "## ✅ Ready for Review\n"
            "Get `/lgtm` approval from the listed approvers below.\n\n",
            "## 🔍 AppSRE Review Required\n",
            1,
        )
        assert reused_review_message == existing_review_message
