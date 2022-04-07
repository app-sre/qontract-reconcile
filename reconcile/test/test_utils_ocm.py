import pytest
from reconcile.utils.ocm import OCM


@pytest.fixture
def ocm(mocker):
    mocker.patch("reconcile.utils.ocm.OCM._init_access_token")
    mocker.patch("reconcile.utils.ocm.OCM._init_request_headers")
    mocker.patch("reconcile.utils.ocm.OCM._init_clusters")
    mocker.patch("reconcile.utils.ocm.OCM._init_blocked_versions")
    return OCM("name", "url", "tid", "turl", "ot")


def test_get_cluster_aws_account_id_none(mocker, ocm):
    role_grants_mock = mocker.patch.object(
        ocm, "get_aws_infrastructure_access_role_grants"
    )
    role_grants_mock.return_value = []
    result = ocm.get_cluster_aws_account_id("cluster")
    assert result is None


def test_get_cluster_aws_account_id_ok(mocker, ocm):
    console_url = (
        "https://signin.aws.amazon.com/switchrole?account=12345&roleName=role-1"
    )
    expected = "12345"
    role_grants_mock = mocker.patch.object(
        ocm, "get_aws_infrastructure_access_role_grants"
    )
    role_grants_mock.return_value = [(None, None, None, console_url)]
    result = ocm.get_cluster_aws_account_id("cluster")
    assert result == expected


@pytest.fixture
def clusters_by_readiness():
    return [
        ({"managed": False, "state": "ready", "storage_quota": 42}, False),
        ({"managed": True, "state": "ready", "storage_quota": 42}, True),
        ({"managed": True, "state": "not ready", "storage_quota": 42}, False),
        # ROSA-like cluster
        ({"managed": True, "state": "ready"}, False),
    ]


def test__ready_for_app_interface(clusters_by_readiness, ocm):
    for cluster, readiness in clusters_by_readiness:
        assert ocm._ready_for_app_interface(cluster) == readiness
