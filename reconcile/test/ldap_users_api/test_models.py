import pytest
from pydantic import ValidationError

from reconcile.ldap_users_api.models import PathSpec, PathType, UserPaths


def test_path_type_values() -> None:
    """Test that all 7 enum values exist."""
    assert PathType.USER.value == "user"
    assert PathType.REQUEST.value == "request"
    assert PathType.QUERY.value == "query"
    assert PathType.GABI.value == "gabi"
    assert PathType.AWS_ACCOUNTS.value == "aws_accounts"
    assert PathType.SCHEDULE.value == "schedule"
    assert PathType.SRE_CHECKPOINT.value == "sre_checkpoint"
    assert len(PathType) == 7


@pytest.mark.parametrize(
    ("input_path", "expected"),
    [
        ("/users/alice.yml", "data/users/alice.yml"),
        ("data/users/bob.yml", "data/users/bob.yml"),
        ("data", "data"),
        ("dataflow/thing.yml", "data/dataflow/thing.yml"),
        ("users/foo.yml", "data/users/foo.yml"),
        ("  /users/alice.yml  ", "data/users/alice.yml"),
    ],
    ids=[
        "leading-slash",
        "already-prefixed",
        "bare-data",
        "dataflow-not-data-prefix",
        "no-leading-slash",
        "whitespace-stripped",
    ],
)
def test_path_spec_prepends_data(input_path: str, expected: str) -> None:
    """Test that PathSpec correctly normalizes paths with data/ prefix."""
    spec = PathSpec(type=PathType.USER, path=input_path)
    assert spec.path == expected


def test_user_paths_frozen() -> None:
    """Test that UserPaths is immutable (frozen)."""
    user_paths = UserPaths(username="alice")
    with pytest.raises(ValidationError):
        user_paths.username = "bob"  # type: ignore[misc]


def test_user_paths_delete_file_types() -> None:
    """Test that delete_file_paths returns USER/REQUEST/QUERY/SRE_CHECKPOINT paths."""
    paths = [
        PathSpec(type=PathType.USER, path="/users/alice.yml"),
        PathSpec(type=PathType.REQUEST, path="/access-requests/req.yml"),
        PathSpec(type=PathType.GABI, path="/gabi/team.yml"),
        PathSpec(type=PathType.QUERY, path="/queries/query.yml"),
        PathSpec(type=PathType.AWS_ACCOUNTS, path="/aws/account.yml"),
        PathSpec(type=PathType.SCHEDULE, path="/schedules/schedule.yml"),
        PathSpec(type=PathType.SRE_CHECKPOINT, path="/checkpoints/alice.yml"),
    ]
    user_paths = UserPaths(username="alice", paths=paths)

    delete_paths = user_paths.delete_file_paths
    assert len(delete_paths) == 4
    assert all(
        p.type
        in {PathType.USER, PathType.REQUEST, PathType.QUERY, PathType.SRE_CHECKPOINT}
        for p in delete_paths
    )


def test_user_paths_modify_file_types() -> None:
    """Test that modify_file_paths returns only GABI/AWS_ACCOUNTS/SCHEDULE paths."""
    paths = [
        PathSpec(type=PathType.USER, path="/users/alice.yml"),
        PathSpec(type=PathType.REQUEST, path="/access-requests/req.yml"),
        PathSpec(type=PathType.GABI, path="/gabi/team.yml"),
        PathSpec(type=PathType.QUERY, path="/queries/query.yml"),
        PathSpec(type=PathType.AWS_ACCOUNTS, path="/aws/account.yml"),
        PathSpec(type=PathType.SCHEDULE, path="/schedules/schedule.yml"),
    ]
    user_paths = UserPaths(username="alice", paths=paths)

    modify_paths = user_paths.modify_file_paths
    assert len(modify_paths) == 3
    assert all(
        p.type in {PathType.GABI, PathType.AWS_ACCOUNTS, PathType.SCHEDULE}
        for p in modify_paths
    )
