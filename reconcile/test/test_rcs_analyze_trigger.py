from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from reconcile.gql_definitions.change_owners.queries.change_types import (
    ChangeTypeImplicitOwnershipJsonPathProviderV1,
)
from reconcile.gql_definitions.change_owners.queries.self_service_roles import (
    DatafileObjectV1,
)
from reconcile.rcs_analyze_trigger import (
    EMOJI_COMPLETED,
    EMOJI_LAUNCHED,
    TRIGGER_COMMAND,
    ComponentDiff,
    RcsAnalyzeJob,
    collect_component_diffs,
    find_trigger_comment,
    is_authorized_approver,
    run,
)
from reconcile.test.change_owners.fixtures import (
    build_change_type,
    build_role,
    build_test_datafile,
)
from reconcile.utils.gitlab_api import Comment
from reconcile.utils.jobcontroller.models import JobConcurrencyPolicy
from reconcile.utils.saas_diff import Definition, State

if TYPE_CHECKING:
    import pytest
    from pytest_mock import MockerFixture

    from reconcile.change_owners.change_types import ChangeTypeProcessor
    from reconcile.change_owners.changes import BundleFileChange
    from reconcile.gql_definitions.change_owners.queries.self_service_roles import (
        RoleV1,
    )


def _emoji_award(name: str) -> MagicMock:
    # MagicMock(name=...) sets the mock's own repr, not a "name" attribute,
    # so it must be assigned separately to be readable as award.name.
    award = MagicMock()
    award.name = name
    return award


def _comment(
    body: str,
    username: str = "someuser",
    comment_id: int = 1,
    created_at: str = "2026-01-01T00:00:00Z",
    awarded_emojis: tuple[str, ...] = (),
    note: MagicMock | None = None,
) -> Comment:
    # Accepting an externally-built note lets callers keep a MagicMock-typed
    # handle to assert on award calls later - going through comment.note
    # would statically resolve to the real (non-mock) gitlab-lib type.
    if note is None:
        note = MagicMock()
    note.awardemojis.list.return_value = [_emoji_award(n) for n in awarded_emojis]
    return Comment(
        id=comment_id, username=username, body=body, created_at=created_at, note=note
    )


def _state(
    saas_file_path: str = "/path.yml",
    saas_file_name: str = "saas-file-name",
    resource_template_name: str = "tmpl",
    cluster: str = "cluster",
    namespace: str = "namespace",
    environment: str = "env-name",
    url: str = "https://github.com/some-org/some-repo.git",
    ref: str = "master",
) -> State:
    return State(
        saas_file_path=saas_file_path,
        saas_file_name=saas_file_name,
        resource_template_name=resource_template_name,
        cluster=cluster,
        namespace=namespace,
        environment=environment,
        url=url,
        ref=ref,
        parameters={},
        secret_parameters={},
        saas_file_definitions=Definition(
            managed_resource_types=[], image_patterns=[], use_channel_in_image_tag=False
        ),
    )


def test_find_trigger_comment_exact_match() -> None:
    comment = _comment(TRIGGER_COMMAND)
    assert find_trigger_comment([comment]) == comment


def test_find_trigger_comment_among_other_lines() -> None:
    comment = _comment(f"some text\n{TRIGGER_COMMAND}\nmore")
    assert find_trigger_comment([comment]) == comment


def test_find_trigger_comment_ignores_rcs_note() -> None:
    assert find_trigger_comment([_comment("/rcs note this is fine")]) is None


def test_find_trigger_comment_ignores_rcs_override() -> None:
    assert find_trigger_comment([_comment("/rcs override justification")]) is None


def test_find_trigger_comment_ignores_unrelated_comment() -> None:
    assert find_trigger_comment([_comment("lgtm, nice work")]) is None


def test_find_trigger_comment_empty_comments() -> None:
    assert find_trigger_comment([]) is None


def test_find_trigger_comment_returns_most_recent_match() -> None:
    older = _comment(TRIGGER_COMMAND, comment_id=1, created_at="2026-01-01T00:00:00Z")
    newer = _comment(TRIGGER_COMMAND, comment_id=2, created_at="2026-01-02T00:00:00Z")
    assert find_trigger_comment([older, newer]) == newer
    assert find_trigger_comment([newer, older]) == newer


def test_collect_component_diffs_finds_ref_change() -> None:
    desired = [_state(ref="new-sha")]
    current = [_state(ref="old-sha")]
    diffs = collect_component_diffs(
        current, desired, changed_paths=[desired[0].saas_file_path]
    )
    assert diffs == [
        ComponentDiff(
            repo_url="https://github.com/some-org/some-repo.git",
            old_ref="old-sha",
            new_ref="new-sha",
        )
    ]


def test_collect_component_diffs_ignores_paths_not_changed() -> None:
    desired = [_state(ref="new-sha")]
    current = [_state(ref="old-sha")]
    diffs = collect_component_diffs(
        current, desired, changed_paths=["/some/other-path.yml"]
    )
    assert diffs == []


def test_collect_component_diffs_ignores_unchanged_ref() -> None:
    desired = [_state(ref="same-sha")]
    current = [_state(ref="same-sha")]
    diffs = collect_component_diffs(
        current, desired, changed_paths=[desired[0].saas_file_path]
    )
    assert diffs == []


def _mock_change_owners_fetch(
    mocker: MockerFixture,
    change_type_processors: list[ChangeTypeProcessor],
    roles: list[RoleV1],
    bundle_changes: list[BundleFileChange],
) -> None:
    # Mocked only at the fetch/query boundary (fetch_bundle_changes /
    # fetch_self_service_roles / gql.get_api hit a live qontract-server) -
    # the real coverage-resolution logic (cover_changes,
    # ChangeTypeContext.includes_approver) runs against the fixtures built
    # above. fetch_self_service_roles/gql.get_api are patched inside
    # change_owners.change_owners, since that's where cover_changes (called
    # directly by is_authorized_approver) resolves them.
    mocker.patch(
        "reconcile.rcs_analyze_trigger.fetch_change_type_processors",
        return_value=change_type_processors,
    )
    mocker.patch(
        "reconcile.change_owners.change_owners.fetch_self_service_roles",
        return_value=roles,
    )
    mocker.patch(
        "reconcile.rcs_analyze_trigger.fetch_bundle_changes",
        return_value=bundle_changes,
    )
    # Configured with a well-shaped empty result (rather than left as a bare
    # unconfigured MagicMock) so that if cover_changes' implicit-ownership
    # pathway ever queries it, it gets a clean "no approver found" instead
    # of confusing MagicMock-shaped garbage.
    mock_gql_get_api = mocker.MagicMock()
    mock_gql_get_api.query.return_value = {"user": [], "bot": []}
    mocker.patch("reconcile.utils.gql.get_api", return_value=mock_gql_get_api)


def _build_scoped_change_type_and_role(
    name: str, schema: str, path: str, users: list[str]
) -> tuple[ChangeTypeProcessor, RoleV1]:
    change_type = build_change_type(
        name=name, change_selectors=["$"], change_schema=schema
    )
    role = build_role(
        name=f"{name}-role",
        change_type_name=name,
        datafiles=[DatafileObjectV1(datafileSchema=schema, path=path)],
        users=users,
    )
    return change_type, role


def test_is_authorized_approver_true_for_the_files_approver(
    mocker: MockerFixture,
) -> None:
    schema = "/schema-1.yml"
    path = "/services/app-a/app.yml"
    change_type, role = _build_scoped_change_type_and_role(
        "ct-a", schema, path, users=["alice"]
    )
    datafile = build_test_datafile(
        content={"ref": "old-sha"}, filepath=path, schema=schema
    )
    bundle_change = datafile.create_bundle_change({"ref": "new-sha"})
    _mock_change_owners_fetch(mocker, [change_type], [role], [bundle_change])

    assert is_authorized_approver(
        "alice",
        mocker.MagicMock(),
        "comparisonsha",
        changed_paths=["data/services/app-a/app.yml"],
    )


def test_is_authorized_approver_false_for_a_different_user(
    mocker: MockerFixture,
) -> None:
    schema = "/schema-1.yml"
    path = "/services/app-a/app.yml"
    change_type, role = _build_scoped_change_type_and_role(
        "ct-a", schema, path, users=["alice"]
    )
    datafile = build_test_datafile(
        content={"ref": "old-sha"}, filepath=path, schema=schema
    )
    bundle_change = datafile.create_bundle_change({"ref": "new-sha"})
    _mock_change_owners_fetch(mocker, [change_type], [role], [bundle_change])

    assert not is_authorized_approver(
        "mallory",
        mocker.MagicMock(),
        "comparisonsha",
        changed_paths=["data/services/app-a/app.yml"],
    )


def test_is_authorized_approver_requires_covering_every_changed_file(
    mocker: MockerFixture,
) -> None:
    # Regression test for a batched MR touching two unrelated components:
    # an approver of only one of them must NOT be authorized to trigger
    # analysis of the whole MR.
    schema = "/schema-1.yml"
    path_a = "/services/app-a/app.yml"
    path_b = "/services/app-b/app.yml"
    change_type_a, role_a = _build_scoped_change_type_and_role(
        "ct-a", schema, path_a, users=["alice"]
    )
    change_type_b, role_b = _build_scoped_change_type_and_role(
        "ct-b", schema, path_b, users=["bob"]
    )
    datafile_a = build_test_datafile(
        content={"ref": "old-sha"}, filepath=path_a, schema=schema
    )
    datafile_b = build_test_datafile(
        content={"ref": "old-sha"}, filepath=path_b, schema=schema
    )
    bundle_changes = [
        datafile_a.create_bundle_change({"ref": "new-sha"}),
        datafile_b.create_bundle_change({"ref": "new-sha"}),
    ]
    _mock_change_owners_fetch(
        mocker, [change_type_a, change_type_b], [role_a, role_b], bundle_changes
    )
    changed_paths = ["data/services/app-a/app.yml", "data/services/app-b/app.yml"]

    assert not is_authorized_approver(
        "alice", mocker.MagicMock(), "comparisonsha", changed_paths
    )
    assert not is_authorized_approver(
        "bob", mocker.MagicMock(), "comparisonsha", changed_paths
    )


def test_is_authorized_approver_requires_covering_every_diff_in_a_file(
    mocker: MockerFixture,
) -> None:
    # Regression test for a single file with two independently-owned
    # fields: an approver of only one of them must NOT be authorized to
    # trigger analysis of the whole file, even though it's a single
    # relevant_changes entry (not a multi-file batch like the test above).
    schema = "/schema-1.yml"
    path = "/services/app-a/app.yml"
    ref_change_type = build_change_type(
        name="ct-ref", change_selectors=["ref"], change_schema=schema
    )
    ref_role = build_role(
        name="ref-role",
        change_type_name="ct-ref",
        datafiles=[DatafileObjectV1(datafileSchema=schema, path=path)],
        users=["alice"],
    )
    permissions_change_type = build_change_type(
        name="ct-permissions", change_selectors=["permissions"], change_schema=schema
    )
    permissions_role = build_role(
        name="permissions-role",
        change_type_name="ct-permissions",
        datafiles=[DatafileObjectV1(datafileSchema=schema, path=path)],
        users=["bob"],
    )
    datafile = build_test_datafile(
        content={"ref": "old-sha", "permissions": "old-perms"},
        filepath=path,
        schema=schema,
    )
    bundle_change = datafile.create_bundle_change({
        "ref": "new-sha",
        "permissions": "new-perms",
    })
    _mock_change_owners_fetch(
        mocker,
        [ref_change_type, permissions_change_type],
        [ref_role, permissions_role],
        [bundle_change],
    )
    changed_paths = ["data/services/app-a/app.yml"]

    assert not is_authorized_approver(
        "alice", mocker.MagicMock(), "comparisonsha", changed_paths
    )
    assert not is_authorized_approver(
        "bob", mocker.MagicMock(), "comparisonsha", changed_paths
    )


def test_is_authorized_approver_true_when_covering_every_diff_in_a_file(
    mocker: MockerFixture,
) -> None:
    # Positive counterpart: a user who owns BOTH independently-owned
    # fields in the same file must still be authorized.
    schema = "/schema-1.yml"
    path = "/services/app-a/app.yml"
    ref_change_type = build_change_type(
        name="ct-ref", change_selectors=["ref"], change_schema=schema
    )
    ref_role = build_role(
        name="ref-role",
        change_type_name="ct-ref",
        datafiles=[DatafileObjectV1(datafileSchema=schema, path=path)],
        users=["alice"],
    )
    permissions_change_type = build_change_type(
        name="ct-permissions", change_selectors=["permissions"], change_schema=schema
    )
    permissions_role = build_role(
        name="permissions-role",
        change_type_name="ct-permissions",
        datafiles=[DatafileObjectV1(datafileSchema=schema, path=path)],
        users=["alice"],
    )
    datafile = build_test_datafile(
        content={"ref": "old-sha", "permissions": "old-perms"},
        filepath=path,
        schema=schema,
    )
    bundle_change = datafile.create_bundle_change({
        "ref": "new-sha",
        "permissions": "new-perms",
    })
    _mock_change_owners_fetch(
        mocker,
        [ref_change_type, permissions_change_type],
        [ref_role, permissions_role],
        [bundle_change],
    )

    assert is_authorized_approver(
        "alice",
        mocker.MagicMock(),
        "comparisonsha",
        changed_paths=["data/services/app-a/app.yml"],
    )


def test_is_authorized_approver_covers_implicit_ownership(
    mocker: MockerFixture,
) -> None:
    # Exercises the implicit-ownership coverage pathway (unlike every other
    # is_authorized_approver test, which only covers self-service roles) -
    # cover_changes runs this branch on every call in production, so it
    # must be tested against the real GqlApproverResolver, not skipped.
    schema = "/schema-1.yml"
    path = "/services/app-a/app.yml"
    change_type = build_change_type(
        name="ct-implicit", change_selectors=["ref"], change_schema=schema
    )
    change_type.implicit_ownership = [
        ChangeTypeImplicitOwnershipJsonPathProviderV1(
            provider="jsonPath",
            jsonPathSelector="$.owner",
        )
    ]
    datafile = build_test_datafile(
        content={"ref": "old-sha", "owner": "/user/alice.yml"},
        filepath=path,
        schema=schema,
    )
    bundle_change = datafile.create_bundle_change({"ref": "new-sha"})
    # No self-service roles at all - coverage must come purely from the
    # implicit-ownership pathway being exercised.
    _mock_change_owners_fetch(mocker, [change_type], [], [bundle_change])

    comparison_gql_api = mocker.MagicMock()
    comparison_gql_api.query.return_value = {
        "user": [{"org_username": "alice", "tag_on_merge_requests": False}],
        "bot": [],
    }
    changed_paths = ["data/services/app-a/app.yml"]

    assert is_authorized_approver(
        "alice", comparison_gql_api, "comparisonsha", changed_paths
    )
    assert not is_authorized_approver(
        "mallory", comparison_gql_api, "comparisonsha", changed_paths
    )


def test_is_authorized_approver_false_when_no_relevant_changes(
    mocker: MockerFixture,
) -> None:
    schema = "/schema-1.yml"
    path = "/services/app-a/app.yml"
    change_type, role = _build_scoped_change_type_and_role(
        "ct-a", schema, path, users=["alice"]
    )
    datafile = build_test_datafile(
        content={"ref": "old-sha"}, filepath=path, schema=schema
    )
    bundle_change = datafile.create_bundle_change({"ref": "new-sha"})
    _mock_change_owners_fetch(mocker, [change_type], [role], [bundle_change])

    assert not is_authorized_approver(
        "alice",
        mocker.MagicMock(),
        "comparisonsha",
        changed_paths=["data/some/unrelated/path.yml"],
    )


def test_is_authorized_approver_does_not_match_on_path_suffix_collision(
    mocker: MockerFixture,
) -> None:
    # Regression test: a changed path that merely ENDS with the bundle
    # file's path (but isn't actually it) must not be treated as a match -
    # exact-match on the reconstructed repo path, not endswith.
    schema = "/schema-1.yml"
    path = "/team-a/app.yml"
    change_type, role = _build_scoped_change_type_and_role(
        "ct-a", schema, path, users=["alice"]
    )
    datafile = build_test_datafile(
        content={"ref": "old-sha"}, filepath=path, schema=schema
    )
    bundle_change = datafile.create_bundle_change({"ref": "new-sha"})
    _mock_change_owners_fetch(mocker, [change_type], [role], [bundle_change])

    # "data/team-b/nested/team-a/app.yml" ends with "/team-a/app.yml" - an
    # endswith-based match would have wrongly treated this as the same file.
    assert not is_authorized_approver(
        "alice",
        mocker.MagicMock(),
        "comparisonsha",
        changed_paths=["data/team-b/nested/team-a/app.yml"],
    )


def _job(**overrides: object) -> RcsAnalyzeJob:
    defaults: dict[str, object] = {
        "gitlab_project_id": "123",
        "gitlab_merge_request_iid": "456",
        "trigger_comment_id": 789,
        "triggered_by": "someuser",
        "triggered_at": "2026-01-01T00:00:00Z",
        "diffs": [],
        "rcs_job_image": "quay.io/example/rcs:latest",
        "rcs_secrets": {"RCS_GITLAB_TOKEN": "token"},
    }
    defaults.update(overrides)
    return RcsAnalyzeJob(**defaults)


def test_rcs_analyze_job_unit_of_work_identity() -> None:
    job = _job()
    assert job.unit_of_work_identity() == ("123", "456", 789)


def test_rcs_analyze_job_identity_depends_only_on_trigger_comment() -> None:
    # Same trigger comment, different "who" fields recorded for audit
    # purposes only, must not change job identity - it's the comment that
    # defines the unit of work, not who posted it or when it was processed.
    job_a = _job(triggered_by="alice", triggered_at="2026-01-01T00:00:00Z")
    job_b = _job(triggered_by="bob", triggered_at="2026-06-01T00:00:00Z")
    assert job_a.unit_of_work_identity() == job_b.unit_of_work_identity()

    # A different trigger comment must produce a different identity, even
    # for the exact same MR.
    job_c = _job(trigger_comment_id=999)
    assert job_c.unit_of_work_identity() != job_a.unit_of_work_identity()


def test_rcs_analyze_job_secret_data() -> None:
    job = _job()
    assert job.secret_data() == {"RCS_GITLAB_TOKEN": "token"}


def test_rcs_analyze_job_spec_contains_expected_env_vars() -> None:
    job = _job(
        triggered_by="alice",
        triggered_at="2026-01-01T00:00:00Z",
        trigger_comment_id=789,
        diffs=[
            ComponentDiff(
                repo_url="https://github.com/some-org/some-repo.git",
                old_ref="old-sha",
                new_ref="new-sha",
            )
        ],
    )
    spec = job.job_spec()
    container = spec.template.spec.containers[0]
    assert container.image == "quay.io/example/rcs:latest"
    env_by_name = {e.name: e.value for e in container.env if e.value is not None}
    assert env_by_name["RCS_APP_INTERFACE_PROJECT_ID"] == "123"
    assert env_by_name["RCS_APP_INTERFACE_MR_IID"] == "456"
    assert env_by_name["RCS_TRIGGERED_BY"] == "alice"
    assert env_by_name["RCS_TRIGGERED_AT"] == "2026-01-01T00:00:00Z"
    assert env_by_name["RCS_TRIGGER_COMMENT_ID"] == "789"
    assert "RCS_COMPONENT_DIFFS" in env_by_name
    assert spec.ttl_seconds_after_finished is not None
    assert spec.active_deadline_seconds is not None
    assert container.resources.requests
    assert container.resources.limits


def _mock_run_dependencies(
    mocker: MockerFixture, comments: list[Comment]
) -> dict[str, MagicMock]:
    mock_gl = mocker.MagicMock()
    mock_gl.__enter__.return_value = mock_gl
    mock_gl.get_merge_request_comments.return_value = comments
    mock_gl.get_merge_request_changed_paths.return_value = ["/path.yml"]
    mocker.patch("reconcile.rcs_analyze_trigger.GitLabApi", return_value=mock_gl)
    mocker.patch("reconcile.rcs_analyze_trigger.queries.get_gitlab_instance")
    mocker.patch("reconcile.rcs_analyze_trigger.get_app_interface_vault_settings")
    # By default, authorize the trigger commenter - tests of the
    # authorization gate itself override this.
    mock_is_authorized_approver = mocker.patch(
        "reconcile.rcs_analyze_trigger.is_authorized_approver",
        return_value=True,
    )
    mock_secret_reader = mocker.MagicMock()
    mock_secret_reader.read_all.return_value = {"RCS_GITLAB_TOKEN": "token"}
    mocker.patch(
        "reconcile.rcs_analyze_trigger.create_secret_reader",
        return_value=mock_secret_reader,
    )
    mocker.patch("reconcile.rcs_analyze_trigger.gql.get_api_for_sha")
    mocker.patch("reconcile.rcs_analyze_trigger.SaasFileList")
    mocker.patch(
        "reconcile.rcs_analyze_trigger.collect_state",
        side_effect=[[_state(ref="old-sha")], [_state(ref="new-sha")]],
    )
    mock_controller = mocker.MagicMock()
    mock_controller.enqueue_job.return_value = True
    mock_controller.wait_for_job_completion.return_value = True
    mocker.patch(
        "reconcile.rcs_analyze_trigger.build_job_controller",
        return_value=mock_controller,
    )
    return {
        "gl": mock_gl,
        "controller": mock_controller,
        "is_authorized_approver": mock_is_authorized_approver,
    }


def test_run_skips_when_no_trigger_comment(mocker: MockerFixture) -> None:
    mocks = _mock_run_dependencies(mocker, comments=[_comment("lgtm")])

    run(
        dry_run=False,
        gitlab_project_id="123",
        gitlab_merge_request_id="456",
        comparison_sha="deadbeef",
        job_controller_cluster="cluster",
        job_controller_namespace="namespace",
        rcs_job_image="quay.io/example/rcs:latest",
        rcs_secrets_path="app-sre/rcs/secrets",
    )

    mocks["controller"].enqueue_job.assert_not_called()


def test_run_skips_authorization_check_when_no_diffs(mocker: MockerFixture) -> None:
    # Diffs are computed before authorization, so the expensive
    # authorization pass is skipped entirely when there's nothing to
    # trigger anyway - same identical (old-sha -> old-sha) state means no
    # ref actually changed.
    mocks = _mock_run_dependencies(mocker, comments=[_comment(TRIGGER_COMMAND)])
    mocker.patch(
        "reconcile.rcs_analyze_trigger.collect_state",
        side_effect=[[_state(ref="same-sha")], [_state(ref="same-sha")]],
    )

    run(
        dry_run=False,
        gitlab_project_id="123",
        gitlab_merge_request_id="456",
        comparison_sha="deadbeef",
        job_controller_cluster="cluster",
        job_controller_namespace="namespace",
        rcs_job_image="quay.io/example/rcs:latest",
        rcs_secrets_path="app-sre/rcs/secrets",
    )

    mocks["is_authorized_approver"].assert_not_called()
    mocks["controller"].enqueue_job.assert_not_called()


def test_run_skips_when_trigger_comment_not_authorized_approver(
    mocker: MockerFixture,
) -> None:
    mocks = _mock_run_dependencies(
        mocker, comments=[_comment(TRIGGER_COMMAND, username="rando")]
    )
    mocker.patch(
        "reconcile.rcs_analyze_trigger.is_authorized_approver",
        return_value=False,
    )

    run(
        dry_run=False,
        gitlab_project_id="123",
        gitlab_merge_request_id="456",
        comparison_sha="deadbeef",
        job_controller_cluster="cluster",
        job_controller_namespace="namespace",
        rcs_job_image="quay.io/example/rcs:latest",
        rcs_secrets_path="app-sre/rcs/secrets",
    )

    mocks["controller"].enqueue_job.assert_not_called()


def test_run_does_not_raise_when_authorization_check_fails(
    mocker: MockerFixture,
) -> None:
    mocks = _mock_run_dependencies(mocker, comments=[_comment(TRIGGER_COMMAND)])
    mocker.patch(
        "reconcile.rcs_analyze_trigger.is_authorized_approver",
        side_effect=Exception("broken role file elsewhere in the bundle"),
    )

    # Must not raise - an unrelated bundle misconfiguration must not crash
    # the calling pr_check pipeline.
    run(
        dry_run=False,
        gitlab_project_id="123",
        gitlab_merge_request_id="456",
        comparison_sha="deadbeef",
        job_controller_cluster="cluster",
        job_controller_namespace="namespace",
        rcs_job_image="quay.io/example/rcs:latest",
        rcs_secrets_path="app-sre/rcs/secrets",
    )

    mocks["controller"].enqueue_job.assert_not_called()


def test_run_launches_job_when_triggered(mocker: MockerFixture) -> None:
    note = MagicMock()
    comment = _comment(TRIGGER_COMMAND, username="alice", comment_id=42, note=note)
    mocks = _mock_run_dependencies(mocker, comments=[comment])

    run(
        dry_run=False,
        gitlab_project_id="123",
        gitlab_merge_request_id="456",
        comparison_sha="deadbeef",
        job_controller_cluster="cluster",
        job_controller_namespace="namespace",
        rcs_job_image="quay.io/example/rcs:latest",
        rcs_secrets_path="app-sre/rcs/secrets",
    )

    mocks["controller"].enqueue_job.assert_called_once()
    call_args = mocks["controller"].enqueue_job.call_args
    job = call_args[0][0]
    assert call_args[1]["concurrency_policy"] == JobConcurrencyPolicy.NO_REPLACE
    assert job.trigger_comment_id == 42
    assert job.triggered_by == "alice"
    note.awardemojis.create.assert_any_call({"name": EMOJI_LAUNCHED})
    note.awardemojis.create.assert_any_call({"name": EMOJI_COMPLETED})


def test_run_skips_when_already_launched(mocker: MockerFixture) -> None:
    comment = _comment(TRIGGER_COMMAND, awarded_emojis=(EMOJI_LAUNCHED,))
    mocks = _mock_run_dependencies(mocker, comments=[comment])

    run(
        dry_run=False,
        gitlab_project_id="123",
        gitlab_merge_request_id="456",
        comparison_sha="deadbeef",
        job_controller_cluster="cluster",
        job_controller_namespace="namespace",
        rcs_job_image="quay.io/example/rcs:latest",
        rcs_secrets_path="app-sre/rcs/secrets",
    )

    mocks["controller"].enqueue_job.assert_not_called()


def test_run_does_not_raise_on_non_success_job_status(mocker: MockerFixture) -> None:
    note = MagicMock()
    comment = _comment(TRIGGER_COMMAND, note=note)
    mocks = _mock_run_dependencies(mocker, comments=[comment])
    mocks["controller"].wait_for_job_completion.return_value = False

    run(
        dry_run=False,
        gitlab_project_id="123",
        gitlab_merge_request_id="456",
        comparison_sha="deadbeef",
        job_controller_cluster="cluster",
        job_controller_namespace="namespace",
        rcs_job_image="quay.io/example/rcs:latest",
        rcs_secrets_path="app-sre/rcs/secrets",
    )

    mocks["controller"].get_job_logs.assert_called_once()
    # Awarded regardless of outcome - the marker means "already handled",
    # not "succeeded".
    note.awardemojis.create.assert_any_call({"name": EMOJI_COMPLETED})


def test_run_deletes_job_on_timeout(mocker: MockerFixture) -> None:
    note = MagicMock()
    comment = _comment(TRIGGER_COMMAND, note=note)
    mocks = _mock_run_dependencies(mocker, comments=[comment])
    mocks["controller"].wait_for_job_completion.side_effect = TimeoutError

    run(
        dry_run=False,
        gitlab_project_id="123",
        gitlab_merge_request_id="456",
        comparison_sha="deadbeef",
        job_controller_cluster="cluster",
        job_controller_namespace="namespace",
        rcs_job_image="quay.io/example/rcs:latest",
        rcs_secrets_path="app-sre/rcs/secrets",
    )

    mocks["controller"].delete_job.assert_called_once()
    assert comment.note is not None
    note.awardemojis.create.assert_called_once_with({"name": EMOJI_LAUNCHED})


def test_run_does_not_raise_on_unexpected_job_controller_error(
    mocker: MockerFixture,
) -> None:
    mocks = _mock_run_dependencies(mocker, comments=[_comment(TRIGGER_COMMAND)])
    mocks["controller"].wait_for_job_completion.side_effect = Exception(
        "Failed to lookup job uid for rcs-analyze-xyz"
    )

    # Must not raise - RCS is a best-effort, non-blocking trigger and must
    # never fail the calling pr_check pipeline.
    run(
        dry_run=False,
        gitlab_project_id="123",
        gitlab_merge_request_id="456",
        comparison_sha="deadbeef",
        job_controller_cluster="cluster",
        job_controller_namespace="namespace",
        rcs_job_image="quay.io/example/rcs:latest",
        rcs_secrets_path="app-sre/rcs/secrets",
    )


def test_run_skips_job_launch_in_dry_run(mocker: MockerFixture) -> None:
    mocks = _mock_run_dependencies(mocker, comments=[_comment(TRIGGER_COMMAND)])
    mock_build_job_controller = mocker.patch(
        "reconcile.rcs_analyze_trigger.build_job_controller",
        return_value=mocks["controller"],
    )

    run(
        dry_run=True,
        gitlab_project_id="123",
        gitlab_merge_request_id="456",
        comparison_sha="deadbeef",
        job_controller_cluster="cluster",
        job_controller_namespace="namespace",
        rcs_job_image="quay.io/example/rcs:latest",
        rcs_secrets_path="app-sre/rcs/secrets",
    )

    # dry_run must never reach the point of launching a real job, since
    # K8sJobController's own dry_run flag is not actually enforced.
    mock_build_job_controller.assert_not_called()
    mocks["controller"].enqueue_job.assert_not_called()


def test_run_logs_same_plan_message_in_both_dry_run_modes(
    mocker: MockerFixture, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("INFO")

    for dry_run in (True, False):
        caplog.clear()
        _mock_run_dependencies(
            mocker, comments=[_comment(TRIGGER_COMMAND, username="alice")]
        )

        run(
            dry_run=dry_run,
            gitlab_project_id="123",
            gitlab_merge_request_id="456",
            comparison_sha="deadbeef",
            job_controller_cluster="cluster",
            job_controller_namespace="namespace",
            rcs_job_image="quay.io/example/rcs:latest",
            rcs_secrets_path="app-sre/rcs/secrets",
        )

        assert (
            "Triggering RCS analysis for MR !456 (requested by alice) with "
            "1 component diff(s)" in caplog.text
        )
