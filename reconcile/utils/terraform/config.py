from dataclasses import dataclass


@dataclass
class TerraformS3BackendConfig:
    access_key: str
    secret_key: str
    bucket: str
    key: str
    region: str
