"""AWS IAM Policy validation using AWS Access Analyzer.

This module validates AWS IAM policy documents using the AWS Access Analyzer
ValidatePolicy API, which provides comprehensive validation (100+ checks) including
syntax validation, security warnings, and AWS best practices.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, Literal

from botocore.exceptions import BotoCoreError, ClientError

from qontract_utils.exceptions import IntegrationError

if TYPE_CHECKING:
    from mypy_boto3_accessanalyzer import AccessAnalyzerClient
    from mypy_boto3_accessanalyzer.type_defs import ValidatePolicyFindingTypeDef

PolicyType = Literal["IDENTITY_POLICY", "RESOURCE_POLICY"]

logger = logging.getLogger(__name__)


class AWSPolicyValidationError(IntegrationError):
    """Raised when an AWS policy document fails validation."""

    def __init__(
        self,
        policy_name: str,
        findings: list[ValidatePolicyFindingTypeDef] | list[dict[str, Any]],
    ) -> None:
        """Initialize with policy name and Access Analyzer findings.

        Args:
            policy_name: Name of the policy for error reporting
            findings: List of findings from Access Analyzer ValidatePolicy API
        """
        self.policy_name = policy_name
        self.findings = findings

        finding_lines = "\n".join(
            f"  - {f['issueCode']}: {f['findingDetails']}" for f in findings
        )
        super().__init__(
            f"Policy validation failed for '{policy_name}':\n{finding_lines}"
        )


def validate_aws_policy(
    client: AccessAnalyzerClient,
    policy: str | dict[str, Any],
    policy_name: str,
    policy_type: PolicyType,
) -> None:
    """Validate an AWS policy document using AWS Access Analyzer.

    Uses the AWS Access Analyzer ValidatePolicy API to perform comprehensive
    validation including syntax checks, security warnings, and AWS best practices.
    This provides 100+ validation checks maintained by AWS.

    Args:
        client: Pre-configured boto3 Access Analyzer client
        policy: Policy document as JSON string or dict
        policy_name: Name of the policy for error reporting
        policy_type: Type of policy - must be either "IDENTITY_POLICY" or "RESOURCE_POLICY"

    Raises:
        AWSPolicyValidationError: If the policy has ERROR findings
        IntegrationError: If unable to call the validation API

    References:
        - https://docs.aws.amazon.com/IAM/latest/UserGuide/access-analyzer-policy-validation.html
        - https://docs.aws.amazon.com/access-analyzer/latest/APIReference/API_ValidatePolicy.html
    """
    # Convert to JSON string if dict
    if isinstance(policy, dict):
        try:
            policy_json = json.dumps(policy)
        except (TypeError, ValueError) as e:
            msg = f"Failed to serialize policy '{policy_name}' to JSON: {e}"
            raise IntegrationError(msg) from e
    else:
        policy_json = policy

    try:
        paginator = client.get_paginator("validate_policy")
        findings: list[ValidatePolicyFindingTypeDef] = []
        for page in paginator.paginate(
            policyDocument=policy_json,
            policyType=policy_type,
        ):
            findings.extend(page.get("findings", []))
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "Unknown")
        error_message = e.response.get("Error", {}).get("Message", str(e))

        # Bypass validation and warn on auth/permission issues — credentials may be
        # unavailable in some environments (e.g. dry-run, local dev).
        if error_code in {
            "UnrecognizedClientException",
            "InvalidClientTokenId",
            "SignatureDoesNotMatch",
            "AccessDenied",
            "AccessDeniedException",
        }:
            logger.warning(
                "Skipping policy validation for '%s': AWS authentication/authorization failed. "
                "Error: %s - %s. "
                "Ensure AWS credentials are configured and have 'access-analyzer:ValidatePolicy' permission.",
                policy_name,
                error_code,
                error_message,
            )
            return

        msg = f"Failed to validate policy '{policy_name}' with Access Analyzer: {error_code} - {error_message}"
        raise IntegrationError(msg) from e
    except BotoCoreError as e:
        msg = f"AWS connection error while validating policy '{policy_name}': {e}"
        raise IntegrationError(msg) from e

    # Filter to only ERROR findings - SECURITY_WARNING and WARNING are informational only
    # SECURITY_WARNING findings (like wildcard usage) are acceptable with proper justification
    blocking_findings = [f for f in findings if f["findingType"] == "ERROR"]
    security_warnings = [f for f in findings if f["findingType"] == "SECURITY_WARNING"]

    # Log security warnings for visibility
    if security_warnings:
        logger.debug(
            "Policy '%s' has SECURITY_WARNING findings:\n%s",
            policy_name,
            "\n".join(
                f"  - {f['issueCode']}: {f['findingDetails']}"
                for f in security_warnings
            ),
        )

    if blocking_findings:
        raise AWSPolicyValidationError(policy_name, blocking_findings)
