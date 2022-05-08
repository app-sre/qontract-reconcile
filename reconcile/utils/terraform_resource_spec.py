from dataclasses import field
from pydantic.dataclasses import dataclass
import json
from typing import Any, Mapping, Optional
from reconcile.utils.openshift_resource import OpenshiftResource, build_secret


@dataclass
class TerraformResourceSpec:

    resource: Mapping[str, Any]
    namespace: Mapping[str, Any]
    secret: Mapping[str, str] = field(init=False, default_factory=lambda: {})

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

    def _annotations(self) -> dict[str, str]:
        annotation_str = self.resource.get("annotations")
        if annotation_str:
            return json.loads(annotation_str)
        else:
            return {}

    def get_secret_field(self, field: str) -> Optional[str]:
        return self.secret.get(field)

    def id_object(self) -> "TerraformResourceUniqueKey":
        return TerraformResourceUniqueKey.from_dict(self.resource)

    def build_oc_secret(
        self, integration: str, integration_version: str
    ) -> OpenshiftResource:
        annotations = self._annotations()
        annotations["qontract.recycle"] = "true"

        return build_secret(
            name=self.output_resource_name,
            integration=integration,
            integration_version=integration_version,
            error_details=self.output_resource_name,
            caller_name=self.account,
            annotations=annotations,
            unencoded_data=self.secret,
        )


@dataclass(frozen=True)
class TerraformResourceUniqueKey:

    identifier: str
    provider: str
    account: str

    @property
    def output_prefix(self) -> str:
        return f"{self.identifier}-{self.provider}"

    @staticmethod
    def from_dict(data: Mapping[str, Any]) -> "TerraformResourceUniqueKey":
        return TerraformResourceUniqueKey(
            identifier=data["identifier"],
            provider=data["provider"],
            account=data["account"],
        )


TerraformResourceSpecInventory = Mapping[
    TerraformResourceUniqueKey, TerraformResourceSpec
]
