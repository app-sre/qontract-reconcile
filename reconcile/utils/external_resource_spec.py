from abc import abstractmethod, ABC
from dataclasses import field
from pydantic.dataclasses import dataclass
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


@runtime_checkable
class ExternalResourceProvisioner(Protocol):
    @property
    def name(self) -> str:
        ...

    @abstractmethod
    def dict(self, *args, **kwargs) -> dict[str, Any]:
        ...


@runtime_checkable
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
class OverridableExternalResource(ExternalResource, Protocol):
    @property
    def overrides(self) -> Optional[Any]:
        ...

    @abstractmethod
    def dict(self, *args, **kwargs) -> dict[str, Any]:
        ...


@runtime_checkable
class DefaultableExternalResource(ExternalResource, Protocol):
    @property
    def defaults(self) -> Optional[Any]:
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


@runtime_checkable
class Cluster(Protocol):
    @property
    def name(self) -> str:
        ...


@runtime_checkable
class Namespace(Protocol):
    @property
    def name(self) -> str:
        ...

    @property
    def managed_external_resources(self) -> Optional[bool]:
        ...

    @property
    def cluster(self) -> Cluster:
        ...

    @property
    def external_resources(
        self,
    ) -> Optional[Sequence[Union[NamespaceExternalResource, Any]]]:
        ...

    @abstractmethod
    def dict(self, *args, **kwargs) -> dict[str, Any]:
        ...


RT = TypeVar("RT")
NT = TypeVar("NT")


class ExternalResourceSpecConfig:
    arbitrary_types_allowed = True


@dataclass(config=ExternalResourceSpecConfig)
class ExternalResourceSpec(ABC, Generic[RT, NT]):

    provision_provider: str
    provisioner_name: str
    resource: RT
    namespace: NT
    secret: Mapping[str, str] = field(init=False, default_factory=lambda: {})

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
    def namespace_name(self) -> str:
        ...

    @property
    @abstractmethod
    def cluster_name(self) -> str:
        ...

    @property
    def output_prefix(self) -> str:
        return f"{self.identifier}-{self.provider}"

    def get_secret_field(self, field: str) -> Optional[str]:
        return self.secret.get(field)

    def id_object(self) -> "ExternalResourceUniqueKey":
        return ExternalResourceUniqueKey.from_spec(self)

    @abstractmethod
    def tags(self, integration: str) -> dict[str, str]:
        ...

    def build_oc_secret(
        self, integration: str, integration_version: str
    ) -> OpenshiftResource:
        raise NotImplementedError()

    @property
    def output_resource_name(self) -> str:
        raise NotImplementedError()

    @abstractmethod
    def annotations(self) -> dict[str, str]:
        ...


@dataclass
class DictExternalResourceSpec(
    ExternalResourceSpec[MutableMapping[str, Any], Mapping[str, Any]]
):
    @property
    def provider(self) -> str:
        return self.resource["provider"]

    @property
    def identifier(self) -> str:
        return self.resource["identifier"]

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


DictExternalResourceSpecInventory = MutableMapping[
    ExternalResourceUniqueKey, DictExternalResourceSpec
]


ER = TypeVar("ER", bound=ExternalResource)
NS = TypeVar("NS", bound=Namespace)


EXTERNAL_RESOURCE_SPEC_DEFAULTS_PROPERTY = "defaults"
EXTERNAL_RESOURCE_SPEC_OVERRIDES_PROPERTY = "overrides"


class TypedExternalResourceSpec(ExternalResourceSpec[ER, Namespace], Generic[ER]):
    @property
    def provider(self) -> str:
        return self.resource.provider

    @property
    def identifier(self) -> str:
        return self.resource.identifier

    @property
    def namespace_name(self) -> str:
        return self.namespace.name

    @property
    def cluster_name(self) -> str:
        return self.namespace.cluster.name

    def tags(self, integration: str) -> dict[str, str]:
        return {
            "managed_by_integration": integration,
            "cluster": self.cluster_name,
            "namespace": self.namespace_name,
            # "environment": self.namespace["environment"]["name"],
            # "app": self.namespace["app"]["name"],
        }

    def annotations(self) -> dict[str, str]:
        return {}
