from dataclasses import dataclass, field
import json
from typing import Any, Optional, cast


@dataclass
class TerraformResourceSpec:

    resource: dict[str, Any]
    namespace: dict[str, Any]
    secret: dict[str, str] = field(init=False, default_factory=lambda: {})

    @property
    def provider(self):
        return self.resource.get("provider")

    @property
    def identifier(self):
        return self.resource.get("identifier")

    @property
    def account(self):
        return self.resource.get("account")

    @property
    def namespace_name(self) -> str:
        return self.namespace["name"]

    @property
    def cluster_name(self) -> str:
        return self.namespace["cluster"]["name"]

    @property
    def output_prefix(self):
        return f"{self.identifier}-{self.provider}"

    @property
    def output_resource_name(self):
        return self.resource.get("output_resource_name") or self.output_prefix

    @property
    def annotations(self) -> dict[str, str]:
        annotation_str = self.resource.get("annotations")
        if annotation_str:
            return json.loads(annotation_str)
        else:
            return {}

    def get_secret_field(self, field: str) -> Optional[str]:
        return self.secret.get(field)


@dataclass(frozen=True)
class TerraformResourceIdentifier:

    identifier: str
    provider: str
    account: str

    @property
    def output_prefix(self) -> str:
        return f"{self.identifier}-{self.provider}"

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "TerraformResourceIdentifier":
        if "identifier" not in data or "provider" not in data or "account" not in data:
            raise ValueError(
                "dict does not include required both keys 'identifier' and 'provider'"
            )
        return TerraformResourceIdentifier(
            identifier=cast(str, data["identifier"]),
            provider=cast(str, data["provider"]),
            account=cast(str, data["account"]),
        )

    @staticmethod
    def from_output_prefix(
        output_prefix: str, account: str
    ) -> "TerraformResourceIdentifier":
        identifier, provider = output_prefix.rsplit("-", 1)
        return TerraformResourceIdentifier(
            identifier=identifier,
            provider=provider,
            account=account,
        )


TerraformResourceSpecDict = dict[TerraformResourceIdentifier, TerraformResourceSpec]
