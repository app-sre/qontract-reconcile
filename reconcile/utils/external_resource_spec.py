from abc import ABC, abstractmethod
from dataclasses import field
from pydantic.dataclasses import dataclass
from pydantic.fields import Field
import json
from typing import (
    Any,
    Generic,
    Mapping,
    MutableMapping,
    Optional,
    Protocol,
    TypeVar,
    runtime_checkable,
    Union,
    Sequence,
    cast,
)

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


class ExternalResourceProvisioner(Protocol):
    @property
    def name(self) -> str:
        ...

    @abstractmethod
    def dict(self, *args, **kwargs) -> dict[str, Any]:
        ...


class ExternalResource(Protocol):
    @property
    def provider(self) -> str:
        ...

    @property
    def identifier(self) -> str:
        ...

    @abstractmethod
    def dict(self, *args, **kwargs) -> dict[str, Any]:
        ...


@runtime_checkable
class NamespaceExternalResource(Protocol):
    @property
    def provider(self) -> str:
        ...

    @property
    def provisioner(self) -> ExternalResourceProvisioner:
        ...

    @property
    def resources(self) -> Sequence[ExternalResource]:
        ...


class Namespace(Protocol):
    name: str
    managed_external_resources: Optional[bool]

    @property
    def external_resources(
        self,
    ) -> Optional[Sequence[Union[NamespaceExternalResource, Any]]]:
        ...

    @abstractmethod
    def dict(self, *args, **kwargs) -> dict[str, Any]:
        ...


class IExternalResourceSpec(ABC):
    @property
    @abstractmethod
    def provision_provider(self) -> str:
        ...

    @property
    @abstractmethod
    def provisioner(self) -> Mapping[str, Any]:
        ...

    @property
    @abstractmethod
    def resource(self) -> MutableMapping[str, Any]:
        ...

    @property
    @abstractmethod
    def namespace(self) -> Mapping[str, Any]:
        ...

    @property
    @abstractmethod
    def provider(self) -> str:
        ...

    @property
    @abstractmethod
    def identifier(self) -> str:
        ...

    @property
    @abstractmethod
    def provisioner_name(self) -> str:
        ...

    @property
    @abstractmethod
    def namespace_name(self) -> str:
        ...

    @property
    @abstractmethod
    def cluster_name(self) -> str:
        ...

    @property
    def output_prefix(self) -> str:
        return f"{self.identifier}-{self.provider}"

    @property
    @abstractmethod
    def output_resource_name(self) -> str:
        ...

    @abstractmethod
    def annotations(self) -> dict[str, str]:
        ...

    @abstractmethod
    def tags(self, integration: str) -> dict[str, str]:
        ...

    @property
    @abstractmethod
    def secret(self) -> Mapping[str, str]:
        ...

    def get_secret_field(self, field: str) -> Optional[str]:
        return self.secret.get(field)

    @abstractmethod
    def id_object(self) -> "ExternalResourceUniqueKey":
        ...

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

    @abstractmethod
    def _output_format(self) -> OutputFormat:
        ...


@dataclass
class ExternalResourceSpec(IExternalResourceSpec):

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
    def output_resource_name(self) -> str:
        return self.resource.get("output_resource_name") or self.output_prefix

    def annotations(self) -> dict[str, str]:
        annotation_str = self.resource.get("annotations")
        if annotation_str:
            return json.loads(annotation_str)
        else:
            return {}

    def tags(self, integration: str) -> dict[str, str]:
        return {
            "managed_by_integration": integration,
            "cluster": self.cluster_name,
            "namespace": self.namespace_name,
            "environment": self.namespace["environment"]["name"],
            "app": self.namespace["app"]["name"],
        }

    def id_object(self) -> "ExternalResourceUniqueKey":
        return ExternalResourceUniqueKey.from_spec(self)

    def _output_format(self) -> OutputFormat:
        if self.resource.get("output_format") is not None:
            return OutputFormat(**cast(dict[str, Any], self.resource["output_format"]))
        else:
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


ExternalResourceSpecInventory = MutableMapping[
    ExternalResourceUniqueKey, ExternalResourceSpec
]


T = TypeVar("T", bound=ExternalResource)


class MyConfig:
    arbitrary_types_allowed = True


@dataclass(config=MyConfig)
class TypedExternalResourceSpec(IExternalResourceSpec, Generic[T]):

    namespace_spec: Namespace
    namespace_external_resource: NamespaceExternalResource
    spec: T
    secret: Mapping[str, str] = Field(init=False, default_factory=lambda: {})

    @property
    def provision_provider(self) -> str:
        return self.namespace_external_resource.provider

    @property
    def provisioner(self) -> Mapping[str, Any]:
        return self.namespace_external_resource.provisioner.dict(by_alias=True)

    @property
    def resource(self) -> MutableMapping[str, Any]:
        return self.spec.dict(by_alias=True)

    @property
    def namespace(self) -> Mapping[str, Any]:
        return self.namespace_spec.dict(by_alias=True)

    @property
    def provider(self) -> str:
        return self.spec.provider

    @property
    def identifier(self) -> str:
        return self.spec.identifier

    @property
    def provisioner_name(self) -> str:
        return self.namespace_external_resource.provisioner.name

    @property
    def namespace_name(self) -> str:
        return self.namespace_spec.name

    @property
    def cluster_name(self) -> str:
        raise Exception("Not implemented")

    @property
    def output_resource_name(self) -> str:
        raise Exception("Not implemented")

    def annotations(self) -> dict[str, str]:
        raise Exception("Not implemented")

    def tags(self, integration: str) -> dict[str, str]:
        return {
            "managed_by_integration": integration,
            "cluster": self.cluster_name,
            "namespace": self.namespace_name,
            # TODO (goberlec) add  environment and app - they are not part of the Namespace protocol yet
        }

    def id_object(self) -> "ExternalResourceUniqueKey":
        return ExternalResourceUniqueKey(
            provision_provider=self.provision_provider,
            provisioner_name=self.provisioner_name,
            identifier=self.identifier,
            provider=self.provider,
        )

    def external_resource_spec(self) -> ExternalResourceSpec:
        return ExternalResourceSpec(
            provision_provider=self.provision_provider,
            provisioner=self.provisioner,
            resource=self.resource,
            namespace=self.namespace,
        )

    def _output_format(self) -> OutputFormat:
        raise Exception("Not implemented")
