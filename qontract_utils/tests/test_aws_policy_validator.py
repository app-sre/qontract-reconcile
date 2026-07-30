"""Tests for AWS policy validator using Access Analyzer."""

import json
import logging
from typing import Any
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import BotoCoreError, ClientError
from qontract_utils.aws_policy_validator import (
    AWSPolicyValidationError,
    validate_aws_policy,
)
from qontract_utils.exceptions import IntegrationError


@pytest.fixture
def valid_policy() -> dict[str, Any]:
    """A valid AWS policy for testing."""
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": "s3:GetObject",
                "Resource": "arn:aws:s3:::my-bucket/*",
            }
        ],
    }


@pytest.fixture
def mock_access_analyzer_success() -> MagicMock:
    """Mock Access Analyzer client with no findings."""
    mock_aa = MagicMock()
    mock_aa.get_paginator.return_value.paginate.return_value = [{"findings": []}]
    return mock_aa


@pytest.fixture
def mock_access_analyzer_error_finding() -> MagicMock:
    """Mock Access Analyzer client with ERROR finding."""
    mock_aa = MagicMock()
    mock_aa.get_paginator.return_value.paginate.return_value = [
        {
            "findings": [
                {
                    "findingType": "ERROR",
                    "issueCode": "MISSING_VERSION",
                    "findingDetails": "The policy must include a Version element.",
                }
            ]
        }
    ]
    return mock_aa


@pytest.fixture
def mock_access_analyzer_security_warning() -> MagicMock:
    """Mock Access Analyzer client with SECURITY_WARNING finding."""
    mock_aa = MagicMock()
    mock_aa.get_paginator.return_value.paginate.return_value = [
        {
            "findings": [
                {
                    "findingType": "SECURITY_WARNING",
                    "issueCode": "PASS_ROLE_WITH_STAR_IN_RESOURCE",
                    "findingDetails": "Using a wildcard (*) in the resource can be overly permissive.",
                }
            ]
        }
    ]
    return mock_aa


def test_valid_policy_dict(
    valid_policy: dict[str, Any], mock_access_analyzer_success: MagicMock
) -> None:
    """Test validation of a valid policy as dict."""
    validate_aws_policy(
        mock_access_analyzer_success, valid_policy, "test-policy", "IDENTITY_POLICY"
    )

    mock_access_analyzer_success.get_paginator.assert_called_once_with(
        "validate_policy"
    )
    call_kwargs = (
        mock_access_analyzer_success.get_paginator.return_value.paginate.call_args[1]
    )
    assert call_kwargs["policyType"] == "IDENTITY_POLICY"
    assert json.loads(call_kwargs["policyDocument"]) == valid_policy


def test_valid_policy_json_string(
    valid_policy: dict[str, Any], mock_access_analyzer_success: MagicMock
) -> None:
    """Test validation of a valid policy as JSON string."""
    validate_aws_policy(
        mock_access_analyzer_success,
        json.dumps(valid_policy),
        "test-policy",
        "IDENTITY_POLICY",
    )

    mock_access_analyzer_success.get_paginator.assert_called_once()


def test_resource_policy_type(
    valid_policy: dict[str, Any], mock_access_analyzer_success: MagicMock
) -> None:
    """Test validation with RESOURCE_POLICY type."""
    validate_aws_policy(
        mock_access_analyzer_success, valid_policy, "test-policy", "RESOURCE_POLICY"
    )

    call_kwargs = (
        mock_access_analyzer_success.get_paginator.return_value.paginate.call_args[1]
    )
    assert call_kwargs["policyType"] == "RESOURCE_POLICY"


def test_error_finding_raises_exception(
    valid_policy: dict[str, Any],
    mock_access_analyzer_error_finding: MagicMock,
) -> None:
    """Test that ERROR findings raise AWSPolicyValidationError."""
    with pytest.raises(AWSPolicyValidationError) as exc_info:
        validate_aws_policy(
            mock_access_analyzer_error_finding,
            valid_policy,
            "test-policy",
            "IDENTITY_POLICY",
        )

    assert exc_info.value.policy_name == "test-policy"
    assert "MISSING_VERSION" in str(exc_info.value)
    assert len(exc_info.value.findings) == 1
    assert exc_info.value.findings[0]["findingType"] == "ERROR"


def test_security_warning_logs_but_does_not_raise(
    valid_policy: dict[str, Any],
    mock_access_analyzer_security_warning: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test that SECURITY_WARNING findings are logged but do not raise an exception."""
    with caplog.at_level(logging.DEBUG):
        validate_aws_policy(
            mock_access_analyzer_security_warning,
            valid_policy,
            "test-policy",
            "IDENTITY_POLICY",
        )

    mock_access_analyzer_security_warning.get_paginator.assert_called_once()
    assert "SECURITY_WARNING" in caplog.text
    assert "PASS_ROLE_WITH_STAR_IN_RESOURCE" in caplog.text
    assert "test-policy" in caplog.text


def test_multiple_findings(caplog: pytest.LogCaptureFixture) -> None:
    """Test handling of multiple findings with different types."""
    mock_aa = MagicMock()
    mock_aa.get_paginator.return_value.paginate.return_value = [
        {
            "findings": [
                {
                    "findingType": "ERROR",
                    "issueCode": "ERROR_1",
                    "findingDetails": "Error detail 1",
                },
                {
                    "findingType": "SECURITY_WARNING",
                    "issueCode": "SECURITY_1",
                    "findingDetails": "Security detail 1",
                },
                {
                    "findingType": "WARNING",
                    "issueCode": "WARNING_1",
                    "findingDetails": "Warning detail 1",
                },
            ]
        }
    ]

    policy = {"Version": "2012-10-17", "Statement": []}

    with (
        caplog.at_level(logging.DEBUG),
        pytest.raises(AWSPolicyValidationError) as exc_info,
    ):
        validate_aws_policy(mock_aa, policy, "test-policy", "IDENTITY_POLICY")

    assert len(exc_info.value.findings) == 1
    assert "ERROR_1" in str(exc_info.value)
    assert "SECURITY_WARNING" in caplog.text
    assert "SECURITY_1" in caplog.text


def test_connection_error() -> None:
    """Test handling of AWS connection errors."""
    mock_aa = MagicMock()
    mock_aa.get_paginator.return_value.paginate.side_effect = BotoCoreError()

    policy = {"Version": "2012-10-17", "Statement": []}

    with pytest.raises(IntegrationError) as exc_info:
        validate_aws_policy(mock_aa, policy, "test-policy", "IDENTITY_POLICY")

    error_msg = str(exc_info.value)
    assert "AWS connection error" in error_msg
    assert "test-policy" in error_msg


def test_generic_client_error() -> None:
    """Test handling of generic AWS client errors."""
    mock_aa = MagicMock()
    mock_aa.get_paginator.return_value.paginate.side_effect = ClientError(
        {
            "Error": {
                "Code": "ThrottlingException",
                "Message": "Rate exceeded",
            }
        },
        "ValidatePolicy",
    )

    policy = {"Version": "2012-10-17", "Statement": []}

    with pytest.raises(IntegrationError) as exc_info:
        validate_aws_policy(mock_aa, policy, "test-policy", "IDENTITY_POLICY")

    error_msg = str(exc_info.value)
    assert "Failed to validate policy" in error_msg
    assert "ThrottlingException" in error_msg
    assert "Rate exceeded" in error_msg


def test_non_serializable_policy() -> None:
    """Test handling of non-JSON-serializable policy dict."""

    class NonSerializable:
        pass

    policy = {"Version": "2012-10-17", "Statement": [NonSerializable()]}

    with pytest.raises(IntegrationError) as exc_info:
        validate_aws_policy(MagicMock(), policy, "test-policy", "IDENTITY_POLICY")

    assert "Failed to serialize policy" in str(exc_info.value)


def test_multi_page_pagination() -> None:
    """Test that findings are accumulated across multiple paginator pages."""
    mock_aa = MagicMock()
    mock_aa.get_paginator.return_value.paginate.return_value = [
        {
            "findings": [
                {
                    "findingType": "ERROR",
                    "issueCode": "ERROR_PAGE_1",
                    "findingDetails": "Error on page 1",
                }
            ]
        },
        {
            "findings": [
                {
                    "findingType": "ERROR",
                    "issueCode": "ERROR_PAGE_2",
                    "findingDetails": "Error on page 2",
                }
            ]
        },
    ]

    policy = {"Version": "2012-10-17", "Statement": []}

    with pytest.raises(AWSPolicyValidationError) as exc_info:
        validate_aws_policy(mock_aa, policy, "test-policy", "IDENTITY_POLICY")

    assert len(exc_info.value.findings) == 2
    issue_codes = {f["issueCode"] for f in exc_info.value.findings}
    assert issue_codes == {"ERROR_PAGE_1", "ERROR_PAGE_2"}


@pytest.mark.parametrize(
    "error_code",
    [
        "UnrecognizedClientException",
        "InvalidClientTokenId",
        "SignatureDoesNotMatch",
        "AccessDenied",
        "AccessDeniedException",
    ],
)
def test_auth_error_codes_bypass_validation(
    error_code: str, caplog: pytest.LogCaptureFixture
) -> None:
    """Test that all auth/permission ClientErrors log a warning and bypass validation."""
    mock_aa = MagicMock()
    mock_aa.get_paginator.return_value.paginate.side_effect = ClientError(
        {"Error": {"Code": error_code, "Message": "Auth failure"}},
        "ValidatePolicy",
    )

    policy = {"Version": "2012-10-17", "Statement": []}

    with caplog.at_level(logging.WARNING):
        validate_aws_policy(mock_aa, policy, "test-policy", "IDENTITY_POLICY")

    assert error_code in caplog.text
    assert "access-analyzer:ValidatePolicy" in caplog.text


@pytest.mark.parametrize("finding_type", ["SUGGESTION", "WARNING"])
def test_non_blocking_finding_types_are_silent(finding_type: str) -> None:
    """Test that SUGGESTION and WARNING findings are silently ignored."""
    mock_aa = MagicMock()
    mock_aa.get_paginator.return_value.paginate.return_value = [
        {
            "findings": [
                {
                    "findingType": finding_type,
                    "issueCode": "SOME_CODE",
                    "findingDetails": "Some detail",
                }
            ]
        }
    ]

    policy = {"Version": "2012-10-17", "Statement": []}

    validate_aws_policy(mock_aa, policy, "test-policy", "IDENTITY_POLICY")


def test_page_without_findings_key() -> None:
    """Test that pages missing the 'findings' key are handled gracefully."""
    mock_aa = MagicMock()
    mock_aa.get_paginator.return_value.paginate.return_value = [
        {},  # page with no 'findings' key
        {"findings": []},
    ]

    policy = {"Version": "2012-10-17", "Statement": []}

    validate_aws_policy(mock_aa, policy, "test-policy", "IDENTITY_POLICY")


def test_validation_error_is_integration_error() -> None:
    """Test that AWSPolicyValidationError is a subclass of IntegrationError."""
    err = AWSPolicyValidationError(
        "test-policy",
        [{"issueCode": "MISSING_VERSION", "findingDetails": "Missing version."}],
    )
    assert isinstance(err, IntegrationError)
