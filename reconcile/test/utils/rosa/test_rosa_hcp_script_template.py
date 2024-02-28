import re

import pytest

from reconcile.ocm.types import OCMSpec
from reconcile.test.fixtures import Fixtures
from reconcile.utils.models import data_default_none
from reconcile.utils.rosa.session import rosa_hcp_creation_script


def normalize_script(s: str) -> str:
    return re.sub(r"\n+", "\n", s.strip())


@pytest.fixture
def script_result_fixtures() -> Fixtures:
    return Fixtures("rosa")


@pytest.fixture
def rosa_cluster_spec() -> OCMSpec:
    cluster_data = Fixtures("clusters").get_anymarkup("rosa_hcp_spec_ai.yml")
    return OCMSpec(**data_default_none(OCMSpec, cluster_data))


def test_rosa_hcp_creation_script(
    rosa_cluster_spec: OCMSpec, script_result_fixtures: Fixtures
) -> None:
    expected = script_result_fixtures.get("rosa_hcp_script_result.sh")
    script = rosa_hcp_creation_script(
        cluster_name="cluster-1", cluster=rosa_cluster_spec, dry_run=False
    )
    assert normalize_script(expected) == normalize_script(script)


def test_rosa_hcp_creation_script_no_provisioning_shard(
    rosa_cluster_spec: OCMSpec, script_result_fixtures: Fixtures
) -> None:
    rosa_cluster_spec.spec.provision_shard_id = None
    expected = script_result_fixtures.get(
        "rosa_hcp_script_result_no_provision_shard.sh"
    )
    script = rosa_hcp_creation_script(
        cluster_name="cluster-1", cluster=rosa_cluster_spec, dry_run=False
    )
    assert normalize_script(expected) == normalize_script(script)


def test_rosa_hcp_creation_script_reuse_oidc(
    rosa_cluster_spec: OCMSpec, script_result_fixtures: Fixtures
) -> None:
    rosa_cluster_spec.spec.oidc_endpoint_url = (  # type: ignore[attr-defined]
        "https://rh-oidc.s3.us-east-1.amazonaws.com/abcdefghijklmnopqrstuvwx"
    )
    expected = script_result_fixtures.get("rosa_hcp_script_result_reuse_oidc_config.sh")
    script = rosa_hcp_creation_script(
        cluster_name="cluster-1", cluster=rosa_cluster_spec, dry_run=False
    )
    assert normalize_script(expected) == normalize_script(script)


def test_rosa_hcp_creation_script_uwm_enable(
    rosa_cluster_spec: OCMSpec, script_result_fixtures: Fixtures
) -> None:
    rosa_cluster_spec.spec.disable_user_workload_monitoring = False
    expected = script_result_fixtures.get("rosa_hcp_script_result_uwm_enabled.sh")
    script = rosa_hcp_creation_script(
        cluster_name="cluster-1", cluster=rosa_cluster_spec, dry_run=False
    )
    assert normalize_script(expected) == normalize_script(script)


def test_rosa_hcp_creation_script_private(
    rosa_cluster_spec: OCMSpec, script_result_fixtures: Fixtures
) -> None:
    rosa_cluster_spec.spec.private = True
    expected = script_result_fixtures.get("rosa_hcp_script_result_private.sh")
    script = rosa_hcp_creation_script(
        cluster_name="cluster-1", cluster=rosa_cluster_spec, dry_run=False
    )
    assert normalize_script(expected) == normalize_script(script)


def test_rosa_hcp_creation_script_dry_run(
    rosa_cluster_spec: OCMSpec, script_result_fixtures: Fixtures
) -> None:
    expected = script_result_fixtures.get("rosa_hcp_script_result_dry_run.sh")
    script = rosa_hcp_creation_script(
        cluster_name="cluster-1", cluster=rosa_cluster_spec, dry_run=True
    )
    assert normalize_script(expected) == normalize_script(script)
