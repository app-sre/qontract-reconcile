"""Tests for LDAP users API integration."""

import pytest
from qontract_utils.vcs import Provider

from reconcile.gql_definitions.common.users_with_paths import (
    AppInterfaceSqlQueryV1,
    AWSAccountV1,
    CredentialsRequestV1,
    GabiInstanceV1,
    ScheduleV1,
    SRECheckpointV1,
    UserV1,
)
from reconcile.gql_definitions.fragments.vault_secret import VaultSecret
from reconcile.ldap_users_api.integration import (
    _find_vcs_secret,
    transform_users_with_paths,
)
from reconcile.ldap_users_api.models import PathType
from reconcile.typed_queries.vcs import Vcs


def test_transform_users_with_paths() -> None:
    """Test transform_users_with_paths with all 7 path types."""
    user = UserV1(
        path="/path/to/user.yml",
        org_username="testuser",
        requests=[CredentialsRequestV1(path="/path/to/request1.yml")],
        queries=[AppInterfaceSqlQueryV1(path="/path/to/query1.yml")],
        gabi_instances=[GabiInstanceV1(path="/path/to/gabi1.yml")],
        aws_accounts=[AWSAccountV1(path="/path/to/aws1.yml")],
        schedules=[ScheduleV1(path="/path/to/schedule1.yml")],
        sre_checkpoints=[SRECheckpointV1(path="/path/to/checkpoint1.yml")],
    )

    result = transform_users_with_paths([user])

    assert len(result) == 1
    user_paths = result[0]
    assert user_paths.username == "testuser"
    assert len(user_paths.paths) == 7

    path_types = {p.type for p in user_paths.paths}
    assert path_types == {
        PathType.USER,
        PathType.REQUEST,
        PathType.QUERY,
        PathType.GABI,
        PathType.AWS_ACCOUNTS,
        PathType.SCHEDULE,
        PathType.SRE_CHECKPOINT,
    }

    path_dict = {p.type: p.path for p in user_paths.paths}
    assert path_dict[PathType.USER] == "data/path/to/user.yml"
    assert path_dict[PathType.REQUEST] == "data/path/to/request1.yml"
    assert path_dict[PathType.QUERY] == "data/path/to/query1.yml"
    assert path_dict[PathType.GABI] == "data/path/to/gabi1.yml"
    assert path_dict[PathType.AWS_ACCOUNTS] == "data/path/to/aws1.yml"
    assert path_dict[PathType.SCHEDULE] == "data/path/to/schedule1.yml"
    assert path_dict[PathType.SRE_CHECKPOINT] == "data/path/to/checkpoint1.yml"


def test_transform_users_with_paths_none_optionals() -> None:
    """Test transform_users_with_paths with None optional fields."""
    user = UserV1(
        path="/path/to/user.yml",
        org_username="testuser",
        requests=None,
        queries=None,
        gabi_instances=None,
        aws_accounts=None,
        schedules=None,
        sre_checkpoints=None,
    )

    result = transform_users_with_paths([user])

    assert len(result) == 1
    user_paths = result[0]
    assert user_paths.username == "testuser"
    assert len(user_paths.paths) == 1

    assert user_paths.paths[0].type == PathType.USER
    assert user_paths.paths[0].path == "data/path/to/user.yml"


def test_transform_users_with_paths_multiple_items() -> None:
    """Test transform_users_with_paths with multiple requests/queries/etc."""
    user = UserV1(
        path="/path/to/user.yml",
        org_username="testuser",
        requests=[
            CredentialsRequestV1(path="/path/to/request1.yml"),
            CredentialsRequestV1(path="/path/to/request2.yml"),
        ],
        queries=[
            AppInterfaceSqlQueryV1(path="/path/to/query1.yml"),
            AppInterfaceSqlQueryV1(path="/path/to/query2.yml"),
        ],
        gabi_instances=None,
        aws_accounts=[AWSAccountV1(path="/path/to/aws1.yml")],
        schedules=None,
        sre_checkpoints=None,
    )

    result = transform_users_with_paths([user])

    assert len(result) == 1
    user_paths = result[0]
    assert user_paths.username == "testuser"
    # 1 USER + 2 REQUEST + 2 QUERY + 1 AWS_ACCOUNTS = 6 paths
    assert len(user_paths.paths) == 6

    request_paths = [p for p in user_paths.paths if p.type == PathType.REQUEST]
    query_paths = [p for p in user_paths.paths if p.type == PathType.QUERY]
    aws_paths = [p for p in user_paths.paths if p.type == PathType.AWS_ACCOUNTS]

    assert len(request_paths) == 2
    assert len(query_paths) == 2
    assert len(aws_paths) == 1


# --- _find_vcs_secret ---


def _make_vcs(name: str, url: str) -> Vcs:
    return Vcs(
        name=name,
        url=url,
        token=VaultSecret(
            path="secret/vcs/token", field="token", version=1, format=None
        ),
        provider=Provider.GITLAB,
    )


def test_find_vcs_secret_found() -> None:
    """Test _find_vcs_secret finds matching VCS instance by URL prefix."""
    vcs_instances = [
        _make_vcs("gitlab-cee", "https://gitlab.cee.redhat.com"),
        _make_vcs("github", "https://github.com"),
    ]

    secret = _find_vcs_secret(
        "https://vault.example.com",
        vcs_instances,
        "https://gitlab.cee.redhat.com/service/app-interface",
    )

    assert secret.secret_manager_url == "https://vault.example.com"
    assert secret.path == "secret/vcs/token"
    assert secret.field == "token"


def test_find_vcs_secret_not_found() -> None:
    """Test _find_vcs_secret raises ValueError when no match."""
    vcs_instances = [
        _make_vcs("github", "https://github.com"),
    ]

    with pytest.raises(ValueError, match="No VCS instance found"):
        _find_vcs_secret(
            "https://vault.example.com",
            vcs_instances,
            "https://gitlab.cee.redhat.com/service/app-interface",
        )
