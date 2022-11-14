from abc import abstractmethod
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
    get_args,
    get_origin,
)

import yaml
from reconcile.utils.openshift_resource import (
    OpenshiftResource,
    build_secret,
    SECRET_MAX_KEY_LENGTH,
)

from reconcile import openshift_resources_base
from reconcile.gql_definitions.fragments.resource_file import ResourceFile
import anymarkup


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
    def defaults(self) -> Optional[ResourceFile]:
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
    @property
    def name(self) -> str:
        ...

    @property
    def managed_external_resources(self) -> Optional[bool]:
        ...

    @property
    def external_resources(
        self,
    ) -> Optional[Sequence[Union[NamespaceExternalResource, Any]]]:
        ...

    @abstractmethod
    def dict(self, *args, **kwargs) -> dict[str, Any]:
        ...


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
        return f"{self.identifier}-{self.provider}"

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


EXTERNAL_RESOURCE_SPEC_DEFAULTS_PROPERTY = "defaults"
EXTERNAL_RESOURCE_SPEC_OVERRIDES_PROPERTY = "overrides"


@dataclass(config=MyConfig)
class TypedExternalResourceSpec(ExternalResourceSpec, Generic[T]):

    namespace_spec: Namespace
    namespace_external_resource: NamespaceExternalResource
    spec: T

    def __init__(
        self,
        namespace_spec: Namespace,
        namespace_external_resource: NamespaceExternalResource,
        spec: T,
    ):
        self.namespace_spec = namespace_spec
        self.namespace_external_resource = namespace_external_resource
        self.spec = spec
        super().__init__(
            provision_provider=self.namespace_external_resource.provider,
            provisioner=self.namespace_external_resource.provisioner.dict(
                by_alias=True
            ),
            resource=self.spec.dict(by_alias=True),
            namespace=self.namespace_spec.dict(by_alias=True),
        )

    def get_defaults_data(self) -> dict[str, Any]:
        if isinstance(self.spec, DefaultableExternalResource) and self.spec.defaults:
            try:
                defaults_values = anymarkup.parse(
                    self.spec.defaults.content, force_types=None
                )
                defaults_values.pop("$schema", None)
                return defaults_values
            except anymarkup.AnyMarkupError:
                # todo error handling
                raise Exception("Could not parse data. Skipping resource")
        return {}

    def get_overrides_data(self) -> dict[str, Any]:
        if not isinstance(self.spec, OverridableExternalResource):
            return {}
        if self.spec.overrides is None:
            return {}
        return self.spec.overrides.dict(by_alias=True)

    def is_overridable(self) -> bool:
        return isinstance(self.spec, OverridableExternalResource)

    def get_overridable_fields(self) -> Sequence[str]:
        if isinstance(self.spec, OverridableExternalResource):
            overrides_class = self.spec.__annotations__[
                EXTERNAL_RESOURCE_SPEC_OVERRIDES_PROPERTY
            ]
            is_optional = get_origin(overrides_class) is Union and type(
                None
            ) in get_args(overrides_class)
            if is_optional:
                overrides_class = get_args(overrides_class)[0]
            return overrides_class.__annotations__.keys()
        else:
            raise ValueError("resource is not overridable")

    def resolve(self) -> "TypedExternalResourceSpec[T]":
        if self.is_overridable():
            overrides_data = self.get_overrides_data()
            defaults_data = self.get_defaults_data()

            for field_name in self.get_overridable_fields():
                if overrides_data.get(field_name) is None:
                    overrides_data[field_name] = defaults_data.get(field_name)
        else:
            overrides_data = {}

        new_spec_attr = self.spec.dict(by_alias=True)
        new_spec_attr[EXTERNAL_RESOURCE_SPEC_OVERRIDES_PROPERTY] = overrides_data
        new_spec = type(self.spec)(**new_spec_attr)
        return TypedExternalResourceSpec(
            namespace_spec=self.namespace_spec,
            namespace_external_resource=self.namespace_external_resource,
            spec=new_spec,
        )
