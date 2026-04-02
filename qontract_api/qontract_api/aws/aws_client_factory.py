"""Factory for creating AWS workspace clients."""

from qontract_utils.aws_api_typed.api import AWSApi, AWSStaticCredentials

from qontract_api.aws.aws_workspace_client import AWSWorkspaceClient
from qontract_api.cache import CacheBackend
from qontract_api.config import Settings
from qontract_api.models import Secret
from qontract_api.secret_manager import SecretManager


def create_aws_workspace_client(
    *,
    secret: Secret,
    region: str,
    cache: CacheBackend,
    secret_manager: SecretManager,
    settings: Settings,
) -> AWSWorkspaceClient:
    """Create an AWSWorkspaceClient from a secret reference.

    Resolves credentials via SecretManager and creates the full client stack.

    Args:
        secret: Secret reference for AWS credentials
        region: AWS region for API calls
        cache: Cache backend for distributed caching
        secret_manager: Secret manager for credential resolution
        settings: Application settings
    """
    creds = secret_manager.read_all(secret)
    aws_api = AWSApi(
        AWSStaticCredentials(
            access_key_id=creds["aws_access_key_id"],
            secret_access_key=creds["aws_secret_access_key"],
            region=region,
        )
    )
    return AWSWorkspaceClient(
        aws_api=aws_api,
        cache=cache,
        settings=settings,
    )
