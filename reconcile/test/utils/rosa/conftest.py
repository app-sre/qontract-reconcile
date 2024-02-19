import json
import tempfile
from typing import Generator
from unittest.mock import MagicMock

import httpretty as httpretty_module
import pytest

from reconcile.gql_definitions.fragments.vault_secret import VaultSecret
from reconcile.utils.jobcontroller.controller import K8sJobController
from reconcile.utils.jobcontroller.models import JobStatus
from reconcile.utils.ocm_base_client import OCMAPIClientConfiguration, OCMBaseClient
from reconcile.utils.rosa.rosa_cli import LogHandle, RosaJob
from reconcile.utils.rosa.session import RosaSession
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
def ocm_api_configuration(
    access_token_url: str,
    ocm_url: str,
) -> OCMAPIClientConfiguration:
    return OCMAPIClientConfiguration(
        url=ocm_url,
        access_token_client_id="some_client_id",
        access_token_client_secret=VaultSecret(
            field="some_field",
            path="some_path",
            format=None,
            version=None,
        ),
        access_token_url=access_token_url,
    )


@pytest.fixture
def ocm_api(
    access_token_url: str,
    ocm_url: str,
) -> OCMBaseClient:
    return OCMBaseClient(
        access_token_client_id="some_client_id",
        access_token_client_secret="some_client_secret",
        access_token_url=access_token_url,
        url=ocm_url,
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
    sr = MagicMock(
        spec=SecretReaderBase,
        autospec=True,
    )
    sr.read_secret.return_value = "secret_value"
    return sr


ROSA_CLI_IMAGE = "registry.ci.openshift.org/ci/rosa-aws-cli:latest"


@pytest.fixture
def rosa_cli_image() -> str:
    return ROSA_CLI_IMAGE


@pytest.fixture
def rosa_session(
    ocm_api: OCMBaseClient,
    job_controller: K8sJobController,
    rosa_cli_image: str,
) -> RosaSession:
    return RosaSession(
        aws_account_id="123",
        aws_region="us-east-1",
        ocm_org_id="org-id",
        ocm_api=ocm_api,
        job_controller=job_controller,
        image=rosa_cli_image,
    )


@pytest.fixture
def log_file() -> Generator[str, None, None]:
    with tempfile.NamedTemporaryFile(delete=False) as f:
        f.write(b"line1\nline2\nline3\nline4\nline5\n")
        f.flush()
        yield f.name


@pytest.fixture
def log_handle(log_file: str) -> LogHandle:
    return LogHandle(log_file)


@pytest.fixture
def rosa_job(rosa_cli_image: str) -> RosaJob:
    return RosaJob(
        aws_account_id="123",
        aws_region="us-east-1",
        ocm_org_id="org_id",
        ocm_token="1234567890",
        cmd="rosa whoami",
        image=rosa_cli_image,
        service_account="my-sa",
        extra_annotations={},
    )
