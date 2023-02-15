from dataclasses import dataclass
from typing import Optional


@dataclass
class Integration:
    name: str
    key: str


@dataclass
class VaultSecret:
    path: str
    field: str
    version: Optional[int]
    q_format: Optional[str]


@dataclass
class TerraformStateS3:
    automation_token: VaultSecret
    bucket: str
    region: str
    integration: Integration


@dataclass
class CloudflareAccount:
    name: str
    api_credentials: VaultSecret
    enforce_twofactor: Optional[bool]
    type: Optional[str]
    provider_version: str
