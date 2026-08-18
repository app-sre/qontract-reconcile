"""Unit tests for OcmGroupsService."""

from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

import pytest
from qontract_utils.ocm_api import OcmClusterGroup

from qontract_api.config import OcmSettings, Settings
from qontract_api.integrations.ocm_groups.domain import OcmGroupsCluster, OcmGroupUser
from qontract_api.integrations.ocm_groups.metrics import (
    ocm_groups_managed_clusters,
    ocm_groups_reconcile_errors,
)
from qontract_api.integrations.ocm_groups.schemas import (
    OcmGroupsActionAddUser,
    OcmGroupsActionDeleteUser,
)
from qontract_api.integrations.ocm_groups.service import (
    OcmGroupsService,
    _GroupMembershipState,
    _is_fatal_fetch_error,
)
from qontract_api.models import TaskStatus
from qontract_api.ocm.domain import OcmConnectionParams

OCM_ENVIRONMENT = "prod"
OCM_CONNECTION = OcmConnectionParams(
    secret_manager_url="https://vault.example.com",
    path="ocm/prod",
    ocm_url="https://api.openshift.com",
    access_token_url="https://sso.redhat.com/token",
    access_token_client_id="client-id",
)


def _cluster(
    name: str = "my-cluster",
    cluster_id: str = "cid-1",
    managed_groups: list[str] | None = None,
) -> OcmGroupsCluster:
    return OcmGroupsCluster(
        name=name,
        cluster_id=cluster_id,
        managed_groups=managed_groups or ["dedicated-admins", "cluster-admins"],
    )


def _user(
    cluster: str = "my-cluster",
    group: str = "dedicated-admins",
    user: str = "alice",
) -> OcmGroupUser:
    return OcmGroupUser(cluster=cluster, group=group, user=user)


@pytest.fixture
def mock_cache() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_secret_manager() -> MagicMock:
    return MagicMock()


@pytest.fixture
def settings() -> Settings:
    """Settings with OCM concurrency configured."""
    return Settings(
        ocm=OcmSettings(groups_fetch_concurrency=2),
    )


@pytest.fixture
def mock_workspace_client() -> MagicMock:
    """Mock OcmWorkspaceClient, with __enter__ returning self like the real client."""
    m = MagicMock()
    m.get_cluster_groups.return_value = []
    m.__enter__.return_value = m
    m.__exit__.return_value = False
    return m


@pytest.fixture(autouse=True)
def patch_workspace_client_factory(
    mock_workspace_client: MagicMock,
) -> Generator[MagicMock]:
    with patch(
        "qontract_api.integrations.ocm_groups.service.create_ocm_workspace_client",
        return_value=mock_workspace_client,
    ) as mocked:
        yield mocked


@pytest.fixture
def service(
    mock_cache: MagicMock,
    mock_secret_manager: MagicMock,
    settings: Settings,
) -> OcmGroupsService:
    return OcmGroupsService(
        cache=mock_cache,
        secret_manager=mock_secret_manager,
        settings=settings,
    )


# -- _is_fatal_fetch_error --


@pytest.mark.parametrize(
    ("message", "expected_fatal"),
    [
        ("OCM down", True),
        ("Connection timeout", True),
        ("403 Forbidden", True),
        ("500 Internal Server Error", True),
        ("404: group not found", False),
        ("not found in OCM", False),
        ("404: cluster not found", False),
    ],
)
def test_is_fatal_fetch_error(message: str, expected_fatal: bool) -> None:
    assert _is_fatal_fetch_error(RuntimeError(message)) is expected_fatal


# -- _GroupMembershipState model --


def test_group_membership_state_eq_ignores_cluster_id() -> None:
    """Equality only considers (cluster, group, user) - not cluster_id."""
    a = _GroupMembershipState(cluster="c1", group="g", user="u", cluster_id="cid-1")
    b = _GroupMembershipState(
        cluster="c1", group="g", user="u", cluster_id="different-cid"
    )
    assert a == b


def test_group_membership_state_neq_on_user() -> None:
    """Different user means not equal."""
    a = _GroupMembershipState(cluster="c1", group="g", user="alice", cluster_id="cid-1")
    b = _GroupMembershipState(cluster="c1", group="g", user="bob", cluster_id="cid-1")
    assert a != b


def test_group_membership_state_not_hashable() -> None:
    """_GroupMembershipState must not be hashable (prevents accidental set use)."""
    s = _GroupMembershipState(cluster="c1", group="g", user="u", cluster_id="cid-1")
    with pytest.raises(TypeError, match="unhashable"):
        hash(s)


# -- fetch current state --


def test_fetch_current_state_fetches_groups_for_all_clusters(
    service: OcmGroupsService,
    mock_workspace_client: MagicMock,
) -> None:
    """Fetches groups from all clusters and builds current state."""
    mock_workspace_client.get_cluster_groups.return_value = [
        OcmClusterGroup(id="dedicated-admins", users=["alice", "bob"]),
        OcmClusterGroup(id="cluster-admins", users=["carol"]),
    ]
    clusters = [_cluster()]

    result, unresolved, errors = service._fetch_current_state(
        mock_workspace_client, clusters, max_workers=1
    )

    assert len(result) == 3
    assert unresolved == set()
    assert errors == []
    usernames = {s.user for s in result}
    assert usernames == {"alice", "bob", "carol"}


def test_fetch_current_state_skips_unmanaged_groups(
    service: OcmGroupsService,
    mock_workspace_client: MagicMock,
) -> None:
    """Only includes groups that are in the cluster's managed_groups."""
    mock_workspace_client.get_cluster_groups.return_value = [
        OcmClusterGroup(id="dedicated-admins", users=["alice"]),
        OcmClusterGroup(id="cluster-admins", users=["bob"]),
    ]
    # Only dedicated-admins is managed
    clusters = [_cluster(managed_groups=["dedicated-admins"])]

    result, unresolved, _errors = service._fetch_current_state(
        mock_workspace_client, clusters, max_workers=1
    )

    assert len(result) == 1
    assert unresolved == set()
    assert result[0].user == "alice"
    assert result[0].group == "dedicated-admins"


def test_fetch_current_state_skips_invalid_ocm_groups(
    service: OcmGroupsService,
    mock_workspace_client: MagicMock,
) -> None:
    """Skips groups that are not valid OCM groups."""
    mock_workspace_client.get_cluster_groups.return_value = [
        OcmClusterGroup(id="some-other-group", users=["alice"]),
    ]
    clusters = [_cluster(managed_groups=["some-other-group"])]

    result, unresolved, _errors = service._fetch_current_state(
        mock_workspace_client, clusters, max_workers=1
    )

    assert len(result) == 0
    assert unresolved == set()


def test_fetch_current_state_handles_fatal_error(
    service: OcmGroupsService,
    mock_workspace_client: MagicMock,
) -> None:
    """Fatal errors (auth, timeout) are tracked as unresolved AND surfaced in errors."""
    mock_workspace_client.get_cluster_groups.side_effect = RuntimeError("OCM down")
    clusters = [_cluster()]

    result, unresolved, errors = service._fetch_current_state(
        mock_workspace_client, clusters, max_workers=1
    )

    assert result == []
    assert unresolved == {"my-cluster"}
    assert len(errors) == 1
    assert "OCM down" in errors[0]


def test_fetch_current_state_handles_nonfatal_error(
    service: OcmGroupsService,
    mock_workspace_client: MagicMock,
) -> None:
    """Non-fatal errors (404, not found) skip the cluster without surfacing errors."""
    mock_workspace_client.get_cluster_groups.side_effect = RuntimeError(
        "404: group not found"
    )
    clusters = [_cluster()]

    result, unresolved, errors = service._fetch_current_state(
        mock_workspace_client, clusters, max_workers=1
    )

    assert result == []
    assert unresolved == {"my-cluster"}
    assert errors == []  # Non-fatal, so no errors collected


# -- build desired state --


def test_build_desired_state_filters_managed_pairs(
    service: OcmGroupsService,
) -> None:
    """Only includes memberships for managed (cluster, group) pairs."""
    clusters = [_cluster(managed_groups=["dedicated-admins"])]
    raw = [
        _user(group="dedicated-admins", user="alice"),
        _user(group="cluster-admins", user="bob"),  # unmanaged, filtered
    ]

    desired = service._build_desired_state(clusters, raw)

    assert len(desired) == 1
    assert desired[0].user == "alice"
    assert desired[0].cluster_id == "cid-1"


def test_build_desired_state_skips_unknown_cluster(
    service: OcmGroupsService,
) -> None:
    """Desired memberships for clusters not in the cluster list are dropped."""
    clusters = [_cluster(name="known-cluster")]
    raw = [_user(cluster="unknown-cluster", group="dedicated-admins", user="alice")]

    desired = service._build_desired_state(clusters, raw)

    assert desired == []


# -- process adds / deletes --


def test_process_adds_applies_actions(
    mock_workspace_client: MagicMock,
) -> None:
    state = _GroupMembershipState(
        cluster="c1", group="dedicated-admins", user="alice", cluster_id="cid-1"
    )
    actions, applied, errors = OcmGroupsService._process_adds(
        mock_workspace_client, [state], dry_run=False
    )

    assert len(actions) == 1
    assert len(applied) == 1
    assert errors == []
    mock_workspace_client.add_user_to_group.assert_called_once_with(
        "cid-1", "dedicated-admins", "alice"
    )


def test_process_adds_dry_run_skips_apply(
    mock_workspace_client: MagicMock,
) -> None:
    state = _GroupMembershipState(cluster="c1", group="g", user="u", cluster_id="cid-1")
    actions, applied, errors = OcmGroupsService._process_adds(
        mock_workspace_client, [state], dry_run=True
    )

    assert len(actions) == 1
    assert applied == []
    assert errors == []
    mock_workspace_client.add_user_to_group.assert_not_called()


def test_process_adds_collects_errors(
    mock_workspace_client: MagicMock,
) -> None:
    mock_workspace_client.add_user_to_group.side_effect = RuntimeError("OCM error")
    state = _GroupMembershipState(cluster="c1", group="g", user="u", cluster_id="cid-1")
    actions, applied, errors = OcmGroupsService._process_adds(
        mock_workspace_client, [state], dry_run=False
    )

    assert len(actions) == 1
    assert applied == []
    assert len(errors) == 1
    assert "OCM error" in errors[0]


def test_process_deletes_applies_actions(
    mock_workspace_client: MagicMock,
) -> None:
    state = _GroupMembershipState(
        cluster="c1", group="dedicated-admins", user="bob", cluster_id="cid-1"
    )
    actions, applied, errors = OcmGroupsService._process_deletes(
        mock_workspace_client, [state], dry_run=False
    )

    assert len(actions) == 1
    assert len(applied) == 1
    assert errors == []
    mock_workspace_client.delete_user_from_group.assert_called_once_with(
        "cid-1", "dedicated-admins", "bob"
    )


def test_process_deletes_collects_errors(
    mock_workspace_client: MagicMock,
) -> None:
    mock_workspace_client.delete_user_from_group.side_effect = RuntimeError("boom")
    state = _GroupMembershipState(cluster="c1", group="g", user="u", cluster_id="cid-1")
    actions, applied, errors = OcmGroupsService._process_deletes(
        mock_workspace_client, [state], dry_run=False
    )

    assert len(actions) == 1
    assert applied == []
    assert len(errors) == 1
    assert "boom" in errors[0]


# -- reconcile --


def test_reconcile_no_op_when_no_clusters(service: OcmGroupsService) -> None:
    result = service.reconcile(OCM_ENVIRONMENT, OCM_CONNECTION, [], [], dry_run=True)
    assert result.status == TaskStatus.SUCCESS
    assert result.actions == []


def test_reconcile_dry_run(
    service: OcmGroupsService,
    mock_workspace_client: MagicMock,
) -> None:
    """Dry run computes diff but does not apply."""
    mock_workspace_client.get_cluster_groups.return_value = [
        OcmClusterGroup(id="dedicated-admins", users=["alice"]),
    ]

    clusters = [_cluster()]
    desired = [_user(user="bob")]

    result = service.reconcile(
        OCM_ENVIRONMENT, OCM_CONNECTION, clusters, desired, dry_run=True
    )

    assert result.status == TaskStatus.SUCCESS
    assert len(result.actions) == 2  # add bob, remove alice
    assert result.applied_count == 0
    mock_workspace_client.add_user_to_group.assert_not_called()
    mock_workspace_client.delete_user_from_group.assert_not_called()


def test_reconcile_non_dry_run(
    service: OcmGroupsService,
    mock_workspace_client: MagicMock,
) -> None:
    """Non-dry run applies actions."""
    mock_workspace_client.get_cluster_groups.return_value = [
        OcmClusterGroup(id="dedicated-admins", users=["alice"]),
    ]

    clusters = [_cluster()]
    desired = [_user(user="alice"), _user(user="bob")]

    result = service.reconcile(
        OCM_ENVIRONMENT, OCM_CONNECTION, clusters, desired, dry_run=False
    )

    assert result.status == TaskStatus.SUCCESS
    assert len(result.actions) == 1
    assert result.applied_count == 1
    mock_workspace_client.add_user_to_group.assert_called_once_with(
        "cid-1", "dedicated-admins", "bob"
    )


def test_reconcile_filters_invalid_groups(
    service: OcmGroupsService,
    mock_workspace_client: MagicMock,
) -> None:
    """Filters desired state to only valid OCM groups."""
    clusters = [_cluster()]
    desired = [_user(group="invalid-group")]

    result = service.reconcile(
        OCM_ENVIRONMENT, OCM_CONNECTION, clusters, desired, dry_run=True
    )

    assert result.status == TaskStatus.SUCCESS
    assert len(result.actions) == 0


def test_reconcile_partial_failure(
    service: OcmGroupsService,
    mock_workspace_client: MagicMock,
) -> None:
    """Reports errors but continues with other actions."""
    mock_workspace_client.get_cluster_groups.return_value = [
        OcmClusterGroup(id="dedicated-admins", users=[]),
    ]
    mock_workspace_client.add_user_to_group.side_effect = [
        RuntimeError("fail"),
        None,  # second call succeeds
    ]

    clusters = [_cluster()]
    desired = [_user(user="alice"), _user(user="bob")]

    result = service.reconcile(
        OCM_ENVIRONMENT, OCM_CONNECTION, clusters, desired, dry_run=False
    )

    assert result.status == TaskStatus.FAILED
    assert len(result.errors) == 1
    assert result.applied_count == 1


def test_reconcile_excludes_failed_clusters_from_diff_fatal(
    service: OcmGroupsService,
    mock_workspace_client: MagicMock,
) -> None:
    """A fatal cluster-fetch failure must report FAILED and surface the error."""
    mock_workspace_client.get_cluster_groups.side_effect = RuntimeError("OCM down")

    clusters = [_cluster()]
    desired = [_user(user="alice"), _user(user="bob")]

    result = service.reconcile(
        OCM_ENVIRONMENT, OCM_CONNECTION, clusters, desired, dry_run=False
    )

    assert result.status == TaskStatus.FAILED
    assert len(result.actions) == 0
    assert result.applied_count == 0
    assert len(result.errors) == 1
    assert "OCM down" in result.errors[0]
    mock_workspace_client.add_user_to_group.assert_not_called()


def test_reconcile_excludes_failed_clusters_from_diff_nonfatal(
    service: OcmGroupsService,
    mock_workspace_client: MagicMock,
) -> None:
    """A non-fatal cluster-fetch failure (404) skips the cluster without failing."""
    mock_workspace_client.get_cluster_groups.side_effect = RuntimeError(
        "404: cluster not found"
    )

    clusters = [_cluster()]
    desired = [_user(user="alice"), _user(user="bob")]

    result = service.reconcile(
        OCM_ENVIRONMENT, OCM_CONNECTION, clusters, desired, dry_run=False
    )

    assert result.status == TaskStatus.SUCCESS
    assert len(result.actions) == 0
    assert result.applied_count == 0
    assert result.errors == []
    mock_workspace_client.add_user_to_group.assert_not_called()


def test_reconcile_filters_unmanaged_group_desired_state(
    service: OcmGroupsService,
    mock_workspace_client: MagicMock,
) -> None:
    """Desired memberships for unmanaged groups produce no actions."""
    # Cluster only manages dedicated-admins
    clusters = [_cluster(managed_groups=["dedicated-admins"])]
    # Desired state includes cluster-admins (valid OCM group, but unmanaged)
    desired = [_user(group="cluster-admins", user="alice")]

    result = service.reconcile(
        OCM_ENVIRONMENT, OCM_CONNECTION, clusters, desired, dry_run=True
    )

    assert len(result.actions) == 0


def test_reconcile_current_state_fetch_error_isolated_per_cluster(
    service: OcmGroupsService,
    mock_workspace_client: MagicMock,
) -> None:
    """One failing cluster does not abort reconciliation of others.

    The failing cluster's fatal error is surfaced in the result, but the
    ok-cluster's actions are still processed.
    """
    failing_cluster = _cluster(name="failing-cluster", cluster_id="cid-fail")
    ok_cluster = _cluster(
        name="ok-cluster",
        cluster_id="cid-ok",
        managed_groups=["dedicated-admins"],
    )

    def _get_groups(cluster_id: str) -> list[OcmClusterGroup]:
        if cluster_id == "cid-fail":
            raise RuntimeError("OCM unreachable")
        return [OcmClusterGroup(id="dedicated-admins", users=["existing"])]

    mock_workspace_client.get_cluster_groups.side_effect = _get_groups

    # Desired: remove 'existing' from ok-cluster (desired is empty)
    desired: list[OcmGroupUser] = []

    result = service.reconcile(
        OCM_ENVIRONMENT,
        OCM_CONNECTION,
        [failing_cluster, ok_cluster],
        desired,
        dry_run=False,
    )

    # ok-cluster's 'existing' user is correctly deleted; failing-cluster's
    # fatal error is surfaced as a reconcile error.
    assert result.status == TaskStatus.FAILED
    assert len(result.applied_actions) == 1
    assert isinstance(result.applied_actions[0], OcmGroupsActionDeleteUser)
    assert result.applied_actions[0].cluster == "ok-cluster"
    assert len(result.errors) == 1
    assert "OCM unreachable" in result.errors[0]


def test_reconcile_current_state_nonfatal_fetch_error_isolated_per_cluster(
    service: OcmGroupsService,
    mock_workspace_client: MagicMock,
) -> None:
    """Non-fatal fetch errors (404) skip the cluster without failing the run."""
    failing_cluster = _cluster(name="failing-cluster", cluster_id="cid-fail")
    ok_cluster = _cluster(
        name="ok-cluster",
        cluster_id="cid-ok",
        managed_groups=["dedicated-admins"],
    )

    def _get_groups(cluster_id: str) -> list[OcmClusterGroup]:
        if cluster_id == "cid-fail":
            raise RuntimeError("404: cluster not found in OCM")
        return [OcmClusterGroup(id="dedicated-admins", users=["existing"])]

    mock_workspace_client.get_cluster_groups.side_effect = _get_groups

    desired: list[OcmGroupUser] = []

    result = service.reconcile(
        OCM_ENVIRONMENT,
        OCM_CONNECTION,
        [failing_cluster, ok_cluster],
        desired,
        dry_run=False,
    )

    # ok-cluster's 'existing' user is correctly deleted; failing-cluster's
    # non-fatal error does not fail the run.
    assert result.status == TaskStatus.SUCCESS
    assert len(result.applied_actions) == 1
    assert isinstance(result.applied_actions[0], OcmGroupsActionDeleteUser)
    assert result.applied_actions[0].cluster == "ok-cluster"
    assert result.errors == []


def test_reconcile_uses_diff_iterables(
    service: OcmGroupsService,
    mock_workspace_client: MagicMock,
) -> None:
    """Verify diff_iterables drives reconciliation (add + delete)."""
    mock_workspace_client.get_cluster_groups.return_value = [
        OcmClusterGroup(id="dedicated-admins", users=["alice"]),
    ]

    clusters = [_cluster()]
    # Desired: bob instead of alice
    desired = [_user(user="bob")]

    result = service.reconcile(
        OCM_ENVIRONMENT, OCM_CONNECTION, clusters, desired, dry_run=True
    )

    assert result.status == TaskStatus.SUCCESS
    add_actions = [a for a in result.actions if isinstance(a, OcmGroupsActionAddUser)]
    del_actions = [
        a for a in result.actions if isinstance(a, OcmGroupsActionDeleteUser)
    ]
    assert len(add_actions) == 1
    assert add_actions[0].user == "bob"
    assert len(del_actions) == 1
    assert del_actions[0].user == "alice"


def test_reconcile_fetch_concurrency(
    mock_cache: MagicMock,
    mock_secret_manager: MagicMock,
    mock_workspace_client: MagicMock,
) -> None:
    """Current-state fetches must run with the configured worker count."""
    settings = Settings(ocm=OcmSettings(groups_fetch_concurrency=3))
    service = OcmGroupsService(
        cache=mock_cache, secret_manager=mock_secret_manager, settings=settings
    )
    cluster = _cluster()

    with patch(
        "qontract_api.integrations.ocm_groups.service.ThreadPoolExecutor",
        wraps=ThreadPoolExecutor,
    ) as mock_executor:
        service.reconcile(OCM_ENVIRONMENT, OCM_CONNECTION, [cluster], [], dry_run=True)

    mock_executor.assert_called_once_with(max_workers=3)


def test_reconcile_exposes_cluster_metrics(
    service: OcmGroupsService,
    mock_workspace_client: MagicMock,
) -> None:
    cluster = _cluster(name="metrics-cluster")

    service.reconcile("test-env-metrics", OCM_CONNECTION, [cluster], [], dry_run=True)

    assert (
        ocm_groups_managed_clusters.labels(
            "ocm-groups", "test-env-metrics", "metrics-cluster"
        )._value.get()
        == 1
    )


def test_reconcile_increments_error_counter_on_failure(
    service: OcmGroupsService,
    mock_workspace_client: MagicMock,
) -> None:
    mock_workspace_client.get_cluster_groups.return_value = [
        OcmClusterGroup(id="dedicated-admins", users=[]),
    ]
    mock_workspace_client.add_user_to_group.side_effect = RuntimeError("boom")

    cluster = _cluster()
    desired = [_user(user="alice")]

    before = ocm_groups_reconcile_errors.labels("ocm-groups", "error-env")._value.get()

    service.reconcile("error-env", OCM_CONNECTION, [cluster], desired, dry_run=False)

    after = ocm_groups_reconcile_errors.labels("ocm-groups", "error-env")._value.get()
    assert after == before + 1


def test_reconcile_multiple_clusters_and_groups(
    service: OcmGroupsService,
    mock_workspace_client: MagicMock,
) -> None:
    """Reconcile works across multiple clusters and groups."""
    c1 = _cluster(name="c1", cluster_id="cid-1")
    c2 = _cluster(name="c2", cluster_id="cid-2")

    def _get_groups(cluster_id: str) -> list[OcmClusterGroup]:
        if cluster_id == "cid-1":
            return [OcmClusterGroup(id="dedicated-admins", users=["alice"])]
        return [OcmClusterGroup(id="cluster-admins", users=["carol"])]

    mock_workspace_client.get_cluster_groups.side_effect = _get_groups

    desired = [
        _user(cluster="c1", group="dedicated-admins", user="alice"),
        _user(cluster="c2", group="cluster-admins", user="dave"),
    ]

    result = service.reconcile(
        OCM_ENVIRONMENT, OCM_CONNECTION, [c1, c2], desired, dry_run=True
    )

    assert result.status == TaskStatus.SUCCESS
    add_actions = [a for a in result.actions if isinstance(a, OcmGroupsActionAddUser)]
    del_actions = [
        a for a in result.actions if isinstance(a, OcmGroupsActionDeleteUser)
    ]
    assert len(add_actions) == 1
    assert add_actions[0].user == "dave"
    assert len(del_actions) == 1
    assert del_actions[0].user == "carol"
