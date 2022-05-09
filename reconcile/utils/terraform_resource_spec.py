from abc import abstractmethod
from dataclasses import field
from pydantic.dataclasses import dataclass
import json
from typing import Any, Mapping, Optional, cast

import yaml
from reconcile.utils.openshift_resource import (
    OpenshiftResource,
    build_secret,
    SECRET_MAX_KEY_LENGTH,
)
from reconcile import openshift_resources_base


class OutputFormatProcessor:
    @abstractmethod
    def render(self, vars: Mapping[str, str]) -> dict[str, str]:
        return {}

    def validate_k8s_secret_key(self, key: Any) -> None:  # pylint: disable=R0201
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
        else:
            return dict(vars)


@dataclass
class OutputFormat:

    provider: str
    data: Optional[str] = None

    @property
    def _formatter(self) -> OutputFormatProcessor:
        if self.provider == "generic-secret":
            return GenericSecretOutputFormatConfig(data=self.data)
        else:
            raise ValueError(f"unknown output format provider {self.provider}")

    def render(self, vars: Mapping[str, str]) -> dict[str, str]:
        return self._formatter.render(vars)


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
            unencoded_data=self._output_format().render(self.secret),
        )

    def _output_format(self) -> OutputFormat:
        if self.resource.get("output_format") is not None:
            return OutputFormat(**cast(dict[str, Any], self.resource["output_format"]))
        else:
            return OutputFormat(provider="generic-secret")


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
