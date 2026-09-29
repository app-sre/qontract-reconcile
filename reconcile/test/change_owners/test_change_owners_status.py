from reconcile.change_owners.bundle import BundleFileType, FileRef
from reconcile.change_owners.change_owners import (
    build_status_message,
    is_app_sre_self_serviceable,
)
from reconcile.change_owners.change_types import ChangeTypeContext
from reconcile.change_owners.decision import ChangeDecision
from reconcile.change_owners.diff import Diff, DiffType
from reconcile.utils.jsonpath import parse_jsonpath


def build_change_decision(self_service_role_name: str | None) -> ChangeDecision:
    file_ref = FileRef(
        file_type=BundleFileType.DATAFILE,
        path="datafile.yaml",
        schema="schema.yaml",
    )
    coverage: list[ChangeTypeContext] = []
    if self_service_role_name:
        coverage.append(
            ChangeTypeContext(
                change_type_processor=None,
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


def test_app_sre_self_serviceable_change_gets_review_queue_guidance() -> None:
    change_decisions = [build_change_decision("app-sre")]
    app_sre_self_serviceable = is_app_sre_self_serviceable(
        self_serviceable=True,
        change_decisions=change_decisions,
    )

    message = build_status_message(
        self_serviceable=True,
        authoritative=True,
        change_admitted=True,
        approver_reachability=set(),
        supported_commands=["/lgtm"],
        app_sre_self_serviceable=app_sre_self_serviceable,
    )

    assert "## ✅ Ready for Review" in message
    assert "Get `/lgtm` approval from the listed approvers below." in message
    assert "review queue" in message
    assert "Please don't ping directly unless this is **urgent**" in message


def test_other_self_service_role_does_not_get_app_sre_guidance() -> None:
    change_decisions = [build_change_decision("another-role")]
    app_sre_self_serviceable = is_app_sre_self_serviceable(
        self_serviceable=True,
        change_decisions=change_decisions,
    )

    message = build_status_message(
        self_serviceable=True,
        authoritative=True,
        change_admitted=True,
        approver_reachability=set(),
        supported_commands=["/lgtm"],
        app_sre_self_serviceable=app_sre_self_serviceable,
    )

    assert "## ✅ Ready for Review" in message
    assert "Get `/lgtm` approval from the listed approvers below." in message
    assert "review queue" not in message
    assert "Please don't ping directly" not in message


def test_non_self_serviceable_change_keeps_existing_app_sre_guidance() -> None:
    change_decisions = [build_change_decision(None)]
    app_sre_self_serviceable = is_app_sre_self_serviceable(
        self_serviceable=False,
        change_decisions=change_decisions,
    )

    message = build_status_message(
        self_serviceable=False,
        authoritative=True,
        change_admitted=True,
        approver_reachability=set(),
        supported_commands=["/lgtm"],
        app_sre_self_serviceable=app_sre_self_serviceable,
    )

    assert (
        message
        == """## 🔍 AppSRE Review Required
**What happens next:**
* AppSRE will review via their [review queue](https://gitlab.cee.redhat.com/service/app-interface-output/-/blob/master/app-interface-review-queue.md)
* Please don't ping directly unless this is **urgent**
* See [etiquette guide](https://gitlab.cee.redhat.com/service/app-interface#app-interface-etiquette) for more info



**Available commands:** `/lgtm`"""
    )
