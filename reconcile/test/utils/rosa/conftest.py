import json
from typing import Callable
from unittest.mock import MagicMock

import httpretty as httpretty_module
import pytest
from boto3 import Session

from reconcile.utils.aws_api import AWSTemporaryCredentials
from reconcile.utils.jobcontroller.controller import K8sJobController
from reconcile.utils.jobcontroller.models import JobStatus
from reconcile.utils.rosa.model import ROSACluster
from reconcile.utils.rosa.session import RosaSessionContextManager, rosa_session_ctx
from reconcile.utils.secret_reader import SecretReaderBase


@pytest.fixture
def access_token_url() -> str:
    return "https://sso/get_token"


@pytest.fixture
def ocm_url() -> str:
    return "http://ocm"


@pytest.fixture(autouse=True)
def ocm_auth_mock(httpretty: httpretty_module, access_token_url: str) -> None:
    httpretty.register_uri(
        httpretty.POST,
        access_token_url,
        body=json.dumps({"access_token": "1234567890"}),
        content_type="text/json",
    )


@pytest.fixture
def account_automation_token() -> tuple[str, str]:
    return "acc_path", "acc_field"


@pytest.fixture
def rosa_cluster(
    access_token_url: str,
    ocm_url: str,
    account_automation_token: tuple[str, str],
    gql_class_factory: Callable[..., ROSACluster],
) -> ROSACluster:
    return gql_class_factory(
        ROSACluster,
        {
            "name": "cluster",
            "spec": {
                "id": "cluster",
                "account": {
                    "name": "account",
                    "uid": "uid",
                    "automationToken": {
                        "path": account_automation_token[0],
                        "field": account_automation_token[1],
                    },
                },
                "product": "rosa",
                "channel": "candidate",
                "region": "us-east-1",
            },
            "ocm": {
                "environment": {
                    "url": ocm_url,
                    "accessTokenClientId": "env_client_id",
                    "accessTokenUrl": access_token_url,
                    "accessTokenClientSecret": {
                        "path": "env_path",
                        "field": "env_field",
                    },
                },
                "orgId": "org_id",
                "accessTokenClientId": "org_client_id",
                "accessTokenUrl": access_token_url,
                "accessTokenClientSecret": {
                    "path": "org_path",
                    "field": "org_field",
                },
            },
        },
    )


@pytest.fixture
def job_controller() -> K8sJobController:
    jc = MagicMock(
        spec=K8sJobController,
        autospec=True,
    )
    jc.store_job_logs.return_value = None
    jc.enqueue_job_and_wait_for_completion.return_value = JobStatus.SUCCESS
    return jc


@pytest.fixture
def secret_reader() -> SecretReaderBase:
    return MagicMock(
        spec=SecretReaderBase,
        autospec=True,
    )


class MockAWSSessionBuilder:
    def build(self) -> Session:
        return MagicMock(spec=Session, autospec=True)

    def build_temporary_credentials(self) -> AWSTemporaryCredentials:
        return AWSTemporaryCredentials(
            access_key_id="access_key_id",
            secret_access_key="secret_access_key",
            session_token="session_token",
            region="region",
        )


@pytest.fixture
def rosa_session_ctx_manager(
    rosa_cluster: ROSACluster,
    job_controller: K8sJobController,
    secret_reader: SecretReaderBase,
) -> RosaSessionContextManager:
    ctx_mgnr = rosa_session_ctx(
        cluster=rosa_cluster,
        job_controller=job_controller,
        secret_reader=secret_reader,
    )
    ctx_mgnr.aws_session_builder = MockAWSSessionBuilder()
    return ctx_mgnr
