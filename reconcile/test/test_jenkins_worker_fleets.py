import logging

import pytest
from pytest_mock import MockerFixture

from reconcile.jenkins_worker_fleets import (
    act,
    get_current_state,
    get_desired_state,
)
from reconcile.test.fixtures import Fixtures
from reconcile.utils.jenkins_api import JenkinsApi
from reconcile.utils.terrascript_aws_client import TerrascriptClient as Terrascript

fixture = Fixtures("jenkins_worker_fleets")


def test_jenkins_worker_fleets(mocker: MockerFixture, caplog):
    mock_get = mocker.patch.object(JenkinsApi, "get_jcasc_config")
    mock_get.return_value = fixture.get_anymarkup("jcasc-export.yml")

    mock_gql = mocker.patch("reconcile.utils.gql.get_api", autospec=True)
    mock_gql.return_value.get_resource.return_value = fixture.get_anymarkup(
        "gql-queries.yml"
    )["gql_resource"]

    mock_apply = mocker.patch.object(JenkinsApi, "apply_jcasc_config")

    instance = fixture.get_anymarkup("gql-queries.yml")["gql_response"]["instances"][0]
    jenkins = JenkinsApi("url", "user", "password")
    terrascript = Terrascript(
        "jenkins-worker-fleets", "", 1, accounts=[], settings=None
    )
    current_state = get_current_state(jenkins)
    workerFleets = instance.get("workerFleets", [])
    desired_state = get_desired_state(terrascript, workerFleets)
    with caplog.at_level(logging.INFO):
        act(False, instance["name"], current_state, desired_state, jenkins)
    mock_apply.assert_called_with(fixture.get_anymarkup("jcasc-apply.yml"))

    assert [rec.message for rec in caplog.records] == [
        "['create_jenkins_worker_fleet', 'ci-int', 'ci-int-jenkins-worker-app-interface']",
        "['delete_jenkins_worker_fleet', 'ci-int', 'ci-int-jenkins-worker-rhel8']",
        "['update_jenkins_worker_fleet', 'ci-int', 'ci-int-jenkins-worker-app-sre']",
    ]


def test_jenkins_worker_fleets_error():
    instance = fixture.get_anymarkup("gql-queries.yml")["gql_response"]["instances"][1]
    terrascript = Terrascript(
        "jenkins-worker-fleets", "", 1, accounts=[], settings=None
    )
    workerFleets = instance.get("workerFleets", [])
    with pytest.raises(ValueError):
        get_desired_state(terrascript, workerFleets)
