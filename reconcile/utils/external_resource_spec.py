import json
from abc import abstractmethod
from collections.abc import (
    Mapping,
    MutableMapping,
)
from dataclasses import field
from typing import (
    Any,
    Optional,
    cast,
)

import yaml
from pydantic import BaseModel
from pydantic.dataclasses import dataclass

from reconcile import openshift_resources_base
from reconcile.utils.metrics import GaugeMetric
from reconcile.utils.openshift_resource import (
    SECRET_MAX_KEY_LENGTH,
    OpenshiftResource,
    build_secret,
)


class OutputFormatProcessor:
    @abstractmethod
    def render(self, vars: Mapping[str, str]) -> dict[str, str]:
        return {}

    def validate_k8s_secret_key(self, key: Any) -> None:
        if isinstance(key, str):
            if len(key) > SECRET_MAX_KEY_LENGTH:
                raise ValueError(
                    f"secret key {key} is longer than {SECRET_MAX_KEY_LENGTH} chars"
                )
        else:
            raise ValueError(f"secret key '{key}' is not a string")

    def validate_k8s_secret_data(self, data: Any) -> None:
        if isinstance(data, dict):
            for k, v in data.items():
                self.validate_k8s_secret_key(k)
                if not isinstance(v, str):
                    raise ValueError(
                        f"dictionary value '{v}' under '{k}' is not a string"
                    )
        else:
            raise ValueError("k8s secret data must be a dictionary")


@dataclass
class GenericSecretOutputFormatConfig(OutputFormatProcessor):
    data: Optional[str] = None

    def render(self, vars: Mapping[str, str]) -> dict[str, str]:
        if self.data:
            # the jinja2 rendering has the capabilitiy to change the passed
            # vars dict - make a copy to protect against it
            rendered_data = openshift_resources_base.process_jinja2_template(
                self.data, dict(vars)
            )
            parsed_data = yaml.safe_load(rendered_data)
            self.validate_k8s_secret_data(parsed_data)
            return cast(dict[str, str], parsed_data)
        return dict(vars)


@dataclass
class OutputFormat:
    provider: str
    data: Optional[str] = None

    @property
    def _formatter(self) -> OutputFormatProcessor:
        if self.provider == "generic-secret":
            return GenericSecretOutputFormatConfig(data=self.data)
        raise ValueError(f"unknown output format provider {self.provider}")

    def render(self, vars: Mapping[str, str]) -> dict[str, str]:
        return self._formatter.render(vars)


@dataclass
class ExternalResourceSpec:
    provision_provider: str
    provisioner: Mapping[str, Any]
    resource: MutableMapping[str, Any]
    namespace: Mapping[str, Any]
    secret: Mapping[str, str] = field(init=False, default_factory=lambda: {})

    @property
    def provider(self) -> str:
        return self.resource["provider"]

    @property
    def identifier(self) -> str:
        return self.resource["identifier"]

    @property
    def provisioner_name(self) -> str:
        return self.provisioner["name"]

    @property
    def namespace_name(self) -> str:
        return self.namespace["name"]

    @property
    def cluster_name(self) -> str:
        return self.namespace["cluster"]["name"]

    @property
    def output_prefix(self) -> str:
        # Adhere to DNS-1123 subdomain names spec. It's reasonable to have provider
        # names that have underscores, but without replacing them with hyphens we run
        # into issues. Alternatively, we could change Cloudflare worker_script to
        # worker-script and prevent the use of underscores going forward.
        #
        # More info can be found at:
        # https://kubernetes.io/docs/concepts/overview/working-with-objects/names/.
        provider = self.provider.replace("_", "-")
        return f"{self.identifier}-{provider}"

    @property
    def output_resource_name(self) -> str:
        return self.resource.get("output_resource_name") or self.output_prefix

    def annotations(self) -> dict[str, str]:
        annotation_str = self.resource.get("annotations")
        if annotation_str:
            return json.loads(annotation_str)
        return {}

    def tags(self, integration: str) -> dict[str, str]:
        return {
            "managed_by_integration": integration,
            "cluster": self.cluster_name,
            "namespace": self.namespace_name,
            "environment": self.namespace["environment"]["name"],
            "app": self.namespace["app"]["name"],
        }

    def get_secret_field(self, field: str) -> Optional[str]:
        return self.secret.get(field)

    def id_object(self) -> "ExternalResourceUniqueKey":
        return ExternalResourceUniqueKey.from_spec(self)

    def build_oc_secret(
        self, integration: str, integration_version: str
    ) -> OpenshiftResource:
        annotations = self.annotations()
        annotations["qontract.recycle"] = "true"

        return build_secret(
            name=self.output_resource_name,
            integration=integration,
            integration_version=integration_version,
            error_details=self.output_resource_name,
            caller_name=self.provisioner_name,
            annotations=annotations,
            unencoded_data=self._output_format().render(self.secret),
        )

    def _output_format(self) -> OutputFormat:
        if self.resource.get("output_format") is not None:
            return OutputFormat(**cast(dict[str, Any], self.resource["output_format"]))
        return OutputFormat(provider="generic-secret")


@dataclass(frozen=True)
class ExternalResourceUniqueKey:
    provision_provider: str
    provisioner_name: str
    identifier: str
    provider: str

    @property
    def output_prefix(self) -> str:
        return f"{self.identifier}-{self.provider}"

    @staticmethod
    def from_spec(spec: ExternalResourceSpec) -> "ExternalResourceUniqueKey":
        return ExternalResourceUniqueKey(
            provision_provider=spec.provision_provider,
            provisioner_name=spec.provisioner_name,
            identifier=spec.identifier,
            provider=spec.provider,
        )


class ExternalResourceBaseMetric(BaseModel):
    "Base class External Resource metrics"

    integration: str


class ExternalResourceInventoryGauge(ExternalResourceBaseMetric, GaugeMetric):
    "Inventory Gauge"

    provision_provider: str
    provisioner_name: str
    provider: str

    @classmethod
    def name(cls) -> str:
        return "qontract_reconcile_external_resource_inventory"


ExternalResourceSpecInventory = MutableMapping[
    ExternalResourceUniqueKey, ExternalResourceSpec
]
