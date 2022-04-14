from dataclasses import field
from pydantic.dataclasses import dataclass
import json
from typing import Any, Mapping, Optional
import base64
from reconcile.utils.openshift_resource import OpenshiftResource


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

    def id_object(self) -> "TerraformResourceIdentifier":
        return TerraformResourceIdentifier.from_dict(self.resource)

    def build_oc_secret(
        self, integration: str, integration_version: str
    ) -> OpenshiftResource:
        annotations = self._annotations()
        annotations["qontract.recycle"] = "true"

        secret_data = {}
        for k, v in self.secret.items():
            if v == "":
                secret_value = None
            else:
                # convert to str to maintain compatability
                # as ports are now ints and not strs
                secret_value = base64.b64encode(str(v).encode()).decode("utf-8")
            secret_data[k] = secret_value

        body = {
            "apiVersion": "v1",
            "kind": "Secret",
            "type": "Opaque",
            "metadata": {"name": self.output_resource_name, "annotations": annotations},
            "data": secret_data,
        }

        return OpenshiftResource(
            body,
            integration,
            integration_version,
            error_details=self.output_resource_name,
            caller_name=self.account,
        )


@dataclass(frozen=True)
class TerraformResourceIdentifier:

    identifier: str
    provider: str
    account: str

    @property
    def output_prefix(self) -> str:
        return f"{self.identifier}-{self.provider}"

    @staticmethod
    def from_dict(data: Mapping[str, Any]) -> "TerraformResourceIdentifier":
        return TerraformResourceIdentifier(**data)


TerraformResourceSpecDict = Mapping[TerraformResourceIdentifier, TerraformResourceSpec]
