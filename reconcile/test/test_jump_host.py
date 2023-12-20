import os
from typing import (
    Any,
    Optional,
)
from unittest.mock import create_autospec

import pytest

from reconcile.utils import gql
from reconcile.utils.jump_host import (
    JumpHostBase,
    JumphostParameters,
    JumpHostSSH,
)

EXPECTED_USER = "test-user"
EXPECTED_HOSTNAME = "test"
EXPECTED_KNOWN_HOSTS_PATH = "path/to/known-hosts"
EXPECTED_KNOWN_HOSTS_CONTENT = "known-hosts-file-content"


@pytest.mark.parametrize(
    "parameters, expected_port",
    [
        (
            # Jumphost with default port
            JumphostParameters(
                hostname=EXPECTED_HOSTNAME,
                key="ABC",
                known_hosts=EXPECTED_KNOWN_HOSTS_PATH,
                local_port=None,
                port=None,
                remote_port=None,
                user=EXPECTED_USER,
            ),
            22,
        ),
        (
            # Jumphost with non-default port
            JumphostParameters(
                hostname=EXPECTED_HOSTNAME,
                key="ABC",
                known_hosts=EXPECTED_KNOWN_HOSTS_PATH,
                local_port=None,
                port=25,
                remote_port=None,
                user=EXPECTED_USER,
            ),
            25,
        ),
    ],
)
def test_base_jumphost(fs: Any, parameters: JumphostParameters, expected_port: int):
    jumphost = JumpHostBase(parameters=parameters)
    assert os.path.exists(jumphost._identity_file)

    with open(jumphost._identity_file, "r", encoding="locale") as f:
        assert f.read() == parameters.key

    assert jumphost._port == expected_port
    assert jumphost._user == EXPECTED_USER
    assert jumphost._hostname == EXPECTED_HOSTNAME


@pytest.mark.parametrize(
    "parameters, local_port, remote_port",
    [
        (
            # Jumphost without remote or local port set
            JumphostParameters(
                hostname=EXPECTED_HOSTNAME,
                key="ABC",
                known_hosts=EXPECTED_KNOWN_HOSTS_PATH,
                local_port=None,
                port=None,
                remote_port=None,
                user=EXPECTED_USER,
            ),
            None,
            None,
        ),
        (
            # Jumphost with remote and local port
            JumphostParameters(
                hostname=EXPECTED_HOSTNAME,
                key="ABC",
                known_hosts=EXPECTED_KNOWN_HOSTS_PATH,
                local_port=25,
                port=None,
                remote_port=30,
                user=EXPECTED_USER,
            ),
            25,
            30,
        ),
    ],
)
def test_ssh_jumphost(
    fs: Any,
    parameters: JumphostParameters,
    local_port: Optional[int],
    remote_port: Optional[int],
):
    gql_mock = create_autospec(spec=gql.GqlApi)
    gql_mock.get_resource.side_effect = [{"content": EXPECTED_KNOWN_HOSTS_CONTENT}]
    jumphost = JumpHostSSH(parameters=parameters, gql_api=gql_mock)
    known_hosts_file = jumphost._identity_dir + "/known_hosts"

    assert os.path.exists(known_hosts_file)
    assert jumphost._remote_port == remote_port
    assert isinstance(jumphost._local_port, int)
    if local_port:
        assert jumphost._local_port == local_port

    with open(known_hosts_file, "r", encoding="locale") as f:
        assert f.read() == EXPECTED_KNOWN_HOSTS_CONTENT
