from dataclasses import dataclass
from typing import Iterable


@dataclass
class AWSAccount:
    automation_token_path: str
    bucket: str

@dataclass
class Integration:
    name: str
    key: str

@dataclass
class TerraformStateS3:
    automation_token_path: str
    bucket: str
    region: str
    integrations: Iterable[Integration]


@dataclass
class CloudflareAccount:
    name: str
    api_credentials_path: str
    enforce_twofactor: bool
    type: str
