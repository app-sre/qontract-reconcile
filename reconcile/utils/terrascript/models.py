from dataclasses import dataclass
from typing import Optional

from reconcile.utils.secret_reader import HasSecret


@dataclass
class Integration:
    name: str
    key: str


@dataclass
class TerraformStateS3:
    automation_token: HasSecret
    bucket: str
    region: str
    integration: Integration


@dataclass
class CloudflareAccount:
    name: str
    api_credentials: HasSecret
    enforce_twofactor: Optional[bool]
    type: Optional[str]
    provider_version: str
