from io import StringIO
from typing import Any
from unittest.mock import MagicMock, Mock, patch

import pytest
from ruamel.yaml import YAML

from reconcile.test.fixtures import Fixtures
from reconcile.utils.mr.cluster_machine_pool_updates import ClustersMachinePoolUpdates
from reconcile.utils.ruamel import create_ruamel_instance


@pytest.fixture
def fxt() -> Fixtures:
    return Fixtures("clusters")


@pytest.fixture
def cluster_spec(fxt: Fixtures) -> dict[str, Any]:
    return fxt.get_anymarkup("rosa_hcp_spec_ai.yml")


@pytest.fixture
def cluster_spec_raw(fxt: Fixtures) -> str:
    return fxt.get("rosa_hcp_spec_ai.yml")


@pytest.fixture
def yaml() -> YAML:
    return create_ruamel_instance(explicit_start=True, width=4096)


@pytest.fixture
def gitlab_cli(cluster_spec_raw: str) -> MagicMock:
    cli = MagicMock()
    cli.project.files.get.return_value = cluster_spec_raw.encode()
    return cli


def test_normalized_machine_pool_updates() -> None:
    mr = ClustersMachinePoolUpdates({
        "/path": [
            {
                "id": "worker",
                "instance_type": "m5.xlarge",
                "autoscaling": None,
                "subnet": "subnet-1",
            }
        ]
    })
    assert mr.normalized_machine_pool_updates() == {
        "/path": [
            {
                "id": "worker",
                "instance_type": "m5.xlarge",
                "subnet": "subnet-1",
            }
        ]
    }


@patch.object(ClustersMachinePoolUpdates, "cancel", autospec=True, return_value=None)
def test_mr_machine_pool_update_changes_to_spec(
    cancel_mock: Mock, cluster_spec_raw: str, gitlab_cli: MagicMock, yaml: YAML
) -> None:
    mr = ClustersMachinePoolUpdates({
        "/path": [
            {
                "id": "worker",
                "instance_type": "m5.xlarge",
                "autoscaling": None,
                "subnet": "subnet-1",
            }
        ]
    })
    mr.branch = "abranch"
    mr.process(gitlab_cli)

    with StringIO() as stream:
        cluster_spec = yaml.load(cluster_spec_raw)
        cluster_spec["machinePools"][0]["subnet"] = "subnet-1"
        yaml.dump(cluster_spec, stream)
        new_content = stream.getvalue()

    gitlab_cli.update_file.assert_called_once_with(
        branch_name="abranch",
        file_path="data/path",
        commit_message="update cluster data/path machine-pool fields",
        content=new_content,
    )
    cancel_mock.assert_not_called()


@pytest.mark.parametrize(
    "no_op_changes",
    [
        {"/path": []},
        {},
    ],
)
@patch.object(ClustersMachinePoolUpdates, "cancel", autospec=True, return_value=None)
def test_mr_machine_pool_update_no_changes(
    cancel_mock: Mock,
    cluster_spec_raw: str,
    gitlab_cli: MagicMock,
    yaml: YAML,
    no_op_changes: dict,
) -> None:
    mr = ClustersMachinePoolUpdates(no_op_changes)
    mr.branch = "abranch"
    mr.process(gitlab_cli)

    gitlab_cli.update_file.assert_not_called()
    cancel_mock.assert_called()
