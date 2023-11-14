import hashlib
import json
from collections.abc import Callable
from threading import Lock
from typing import (
    Any,
    Optional,
    Union,
)

from jsonpath_ng.exceptions import JsonPathParserError
from pydantic import (
    BaseModel,
    Extra,
    Field,
    Json,
)

from reconcile.gql_definitions.common.saas_files import (
    AppV1,
    ConfiguredBaseModel,
    DeployResourcesV1,
    ManagedResourceNamesV1,
    PipelinesProviderTektonV1,
    PipelinesProviderV1,
    RoleV1,
    SaasFileAuthenticationV1,
    SaasResourceTemplateTargetImageV1,
    SaasResourceTemplateTargetNamespaceSelectorV1,
    SaasResourceTemplateTargetPromotionV1,
    SaasResourceTemplateTargetUpstreamV1,
    SaasResourceTemplateTargetV2,
    SaasResourceTemplateTargetV2_SaasSecretParametersV1,
    SaasResourceTemplateV2_SaasSecretParametersV1,
    SaasSecretParametersV1,
    SlackOutputV1,
)
from reconcile.gql_definitions.common.saas_files import query as saas_files_query
from reconcile.gql_definitions.common.saas_target_namespaces import (
    query as namespaces_query,
)
from reconcile.gql_definitions.common.saasherder_settings import AppInterfaceSettingsV1
from reconcile.gql_definitions.common.saasherder_settings import (
    query as saasherder_settings_query,
)
from reconcile.gql_definitions.fragments.saas_target_namespace import (
    SaasTargetNamespace,
)
from reconcile.utils import gql
from reconcile.utils.exceptions import (
    AppInterfaceSettingsError,
    ParameterError,
)
from reconcile.utils.jsonpath import parse_jsonpath


class SaasResourceTemplateTarget(ConfiguredBaseModel):
    path: Optional[str] = Field(..., alias="path")
    name: Optional[str] = Field(..., alias="name")
    # the namespace must be required to fulfill the saas file schema (utils.saasherder.interface.SaasFile)
    namespace: SaasTargetNamespace = Field(..., alias="namespace")
    ref: str = Field(..., alias="ref")
    promotion: Optional[SaasResourceTemplateTargetPromotionV1] = Field(
        ..., alias="promotion"
    )
    parameters: Optional[Json] = Field(..., alias="parameters")
    secret_parameters: Optional[
        list[SaasResourceTemplateTargetV2_SaasSecretParametersV1]
    ] = Field(..., alias="secretParameters")
    upstream: Optional[SaasResourceTemplateTargetUpstreamV1] = Field(
        ..., alias="upstream"
    )
    image: Optional[SaasResourceTemplateTargetImageV1] = Field(..., alias="image")
    disable: Optional[bool] = Field(..., alias="disable")
    delete: Optional[bool] = Field(..., alias="delete")

    def uid(
        self, parent_saas_file_name: str, parent_resource_template_name: str
    ) -> str:
        """Returns a unique identifier for a target."""
        return hashlib.blake2s(
            f"{parent_saas_file_name}:{parent_resource_template_name}:{self.name if self.name else 'default'}:{self.namespace.cluster.name}:{self.namespace.name}".encode(),
            digest_size=20,
        ).hexdigest()

    class Config:
        # ignore `namespaceSelector` and 'provider' fields from the GQL schema
        extra = Extra.ignore


class SaasResourceTemplate(ConfiguredBaseModel):
    name: str = Field(..., alias="name")
    url: str = Field(..., alias="url")
    path: str = Field(..., alias="path")
    provider: Optional[str] = Field(..., alias="provider")
    hash_length: Optional[int] = Field(..., alias="hash_length")
    parameters: Optional[Json] = Field(..., alias="parameters")
    secret_parameters: Optional[
        list[SaasResourceTemplateV2_SaasSecretParametersV1]
    ] = Field(..., alias="secretParameters")
    targets: list[SaasResourceTemplateTarget] = Field(..., alias="targets")


class SaasFile(ConfiguredBaseModel):
    path: str = Field(..., alias="path")
    name: str = Field(..., alias="name")
    labels: Optional[Json] = Field(..., alias="labels")
    app: AppV1 = Field(..., alias="app")
    pipelines_provider: Union[PipelinesProviderTektonV1, PipelinesProviderV1] = Field(
        ..., alias="pipelinesProvider"
    )
    deploy_resources: Optional[DeployResourcesV1] = Field(..., alias="deployResources")
    slack: Optional[SlackOutputV1] = Field(..., alias="slack")
    managed_resource_types: list[str] = Field(..., alias="managedResourceTypes")
    takeover: Optional[bool] = Field(..., alias="takeover")
    deprecated: Optional[bool] = Field(..., alias="deprecated")
    compare: Optional[bool] = Field(..., alias="compare")
    timeout: Optional[str] = Field(..., alias="timeout")
    publish_job_logs: Optional[bool] = Field(..., alias="publishJobLogs")
    cluster_admin: Optional[bool] = Field(..., alias="clusterAdmin")
    image_patterns: list[str] = Field(..., alias="imagePatterns")
    allowed_secret_parameter_paths: Optional[list[str]] = Field(
        ..., alias="allowedSecretParameterPaths"
    )
    use_channel_in_image_tag: Optional[bool] = Field(
        ..., alias="use_channel_in_image_tag"
    )
    authentication: Optional[SaasFileAuthenticationV1] = Field(
        ..., alias="authentication"
    )
    parameters: Optional[Json] = Field(..., alias="parameters")
    secret_parameters: Optional[list[SaasSecretParametersV1]] = Field(
        ..., alias="secretParameters"
    )
    validate_targets_in_app: Optional[bool] = Field(..., alias="validateTargetsInApp")
    managed_resource_names: Optional[list[ManagedResourceNamesV1]] = Field(
        ..., alias="managedResourceNames"
    )
    resource_templates: list[SaasResourceTemplate] = Field(
        ..., alias="resourceTemplates"
    )
    self_service_roles: Optional[list[RoleV1]] = Field(..., alias="selfServiceRoles")


class SaasFileList:
    def __init__(
        self,
        name: Optional[str] = None,
        query_func: Optional[Callable] = None,
        namespaces: Optional[list[SaasTargetNamespace]] = None,
    ) -> None:
        # query_func and namespaces are optional args mostly used in tests
        if not query_func:
            query_func = gql.get_api().query
        if not namespaces:
            namespaces = namespaces_query(query_func).namespaces or []
        self.namespaces = namespaces
        self.cluster_namespaces = {
            (ns.cluster.name, ns.name): ns for ns in self.namespaces
        }

        self._init_caches()

        self.saas_files_v2 = saas_files_query(query_func).saas_files or []
        if name:
            self.saas_files_v2 = [sf for sf in self.saas_files_v2 if sf.name == name]
        self.saas_files = self._resolve_namespace_selectors()

    def _init_caches(self) -> None:
        self._namespaces_as_dict_cache: Optional[dict[str, list[Any]]] = None
        self._namespaces_as_dict_lock = Lock()
        self._matching_namespaces_cache: dict[str, Any] = {}
        self._matching_namespaces_lock = Lock()

    def _resolve_namespace_selectors(self) -> list[SaasFile]:
        saas_files: list[SaasFile] = []
        # resolve namespaceSelectors to real namespaces
        for sfv2 in self.saas_files_v2:
            for rt_gql in sfv2.resource_templates:
                for target_gql in rt_gql.targets[:]:
                    # either namespace or namespaceSelector must be set
                    if target_gql.namespace and target_gql.namespace_selector:
                        raise ParameterError(
                            f"SaasFile {sfv2.name}: namespace and namespaceSelector are mutually exclusive"
                        )
                    if not target_gql.provider:
                        target_gql.provider = "static"

                    if (
                        target_gql.namespace_selector
                        and target_gql.provider != "dynamic"
                    ):
                        raise ParameterError(
                            f"SaasFile {sfv2.name}: namespaceSelector can only be used with 'provider: dynamic'"
                        )
                    if (
                        target_gql.namespace_selector
                        and target_gql.provider == "dynamic"
                    ):
                        rt_gql.targets.remove(target_gql)
                        rt_gql.targets += self.create_targets_for_namespace_selector(
                            target_gql, target_gql.namespace_selector
                        )
            # convert SaasFileV2 (with optional resource_templates.targets.namespace field)
            # to SaasFile (with required resource_templates.targets.namespace field)
            saas_files.append(SaasFile(**export_model(sfv2)))
        return saas_files

    def create_targets_for_namespace_selector(
        self,
        target: SaasResourceTemplateTargetV2,
        namespace_selector: SaasResourceTemplateTargetNamespaceSelectorV1,
    ) -> list[SaasResourceTemplateTargetV2]:
        targets = []
        for namespace in self.get_namespaces_by_selector(namespace_selector):
            target_dict = export_model(target)
            target_dict["namespace"] = export_model(namespace)
            targets.append(SaasResourceTemplateTargetV2(**target_dict))
        return targets

    def _get_namespaces_as_dict(self) -> dict[str, list[Any]]:
        # json representation of all the namespaces to filter on
        # remove all the None values to simplify the jsonpath expressions
        if self._namespaces_as_dict_cache is None:
            with self._namespaces_as_dict_lock:
                self._namespaces_as_dict_cache = {
                    "namespace": [
                        ns.dict(by_alias=True, exclude_none=True)
                        for ns in self.namespaces
                    ]
                }
        return self._namespaces_as_dict_cache

    def _matching_namespaces(self, selector: str) -> Any:
        if selector not in self._matching_namespaces_cache:
            with self._matching_namespaces_lock:
                namespaces_as_dict = self._get_namespaces_as_dict()
                try:
                    self._matching_namespaces_cache[selector] = parse_jsonpath(
                        selector
                    ).find(namespaces_as_dict)
                except JsonPathParserError as e:
                    raise ParameterError(
                        f"Invalid jsonpath expression in namespaceSelector '{selector}' :{e}"
                    )

        return self._matching_namespaces_cache[selector]

    def get_namespaces_by_selector(
        self, namespace_selector: SaasResourceTemplateTargetNamespaceSelectorV1
    ) -> list[SaasTargetNamespace]:
        filtered_namespaces: dict[tuple[str, str], Any] = {}

        for include in namespace_selector.json_path_selectors.include:
            for match in self._matching_namespaces(include):
                cluster_name = match.value["cluster"]["name"]
                ns_name = match.value["name"]
                filtered_namespaces[(cluster_name, ns_name)] = self.cluster_namespaces[
                    (cluster_name, ns_name)
                ]

        for exclude in namespace_selector.json_path_selectors.exclude or []:
            for match in self._matching_namespaces(exclude):
                cluster_name = match.value["cluster"]["name"]
                ns_name = match.value["name"]
                filtered_namespaces.pop((cluster_name, ns_name), None)

        return list(filtered_namespaces.values())

    def where(
        self,
        name: Optional[str] = None,
        env_name: Optional[str] = None,
        app_name: Optional[str] = None,
    ) -> list[SaasFile]:
        if name is None and env_name is None and app_name is None:
            return self.saas_files

        if name == "" or env_name == "" or app_name == "":
            return []

        filtered: list[SaasFile] = []
        for saas_file in self.saas_files[:]:
            if name and saas_file.name != name:
                continue

            if app_name and saas_file.app.name != app_name:
                continue

            sf = saas_file.copy(deep=True)
            if env_name:
                for rt in sf.resource_templates[:]:
                    for target in rt.targets[:]:
                        if target.namespace.environment.name != env_name:
                            rt.targets.remove(target)
                    if not rt.targets:
                        sf.resource_templates.remove(rt)
                if not sf.resource_templates:
                    continue
            filtered.append(sf)

        return filtered


def convert_parameters_to_json_string(root: dict[str, Any]) -> dict[str, Any]:
    """Find all parameter occurrences and convert them to a json string."""
    for key, value in root.items():
        if key in ["parameters", "labels"]:
            root[key] = json.dumps(value) if value is not None else None
        elif isinstance(value, dict):
            root[key] = convert_parameters_to_json_string(value)
        elif isinstance(value, list):
            root[key] = [
                convert_parameters_to_json_string(v) if isinstance(v, dict) else v
                for v in value
            ]
    return root


def export_model(model: BaseModel) -> dict[str, Any]:
    return convert_parameters_to_json_string(model.dict(by_alias=True))


def get_saas_files(
    name: Optional[str] = None,
    env_name: Optional[str] = None,
    app_name: Optional[str] = None,
    query_func: Optional[Callable] = None,
    namespaces: Optional[list[SaasTargetNamespace]] = None,
    saas_file_list: Optional[SaasFileList] = None,
) -> list[SaasFile]:
    if not saas_file_list:
        saas_file_list = SaasFileList(
            name=name, query_func=query_func, namespaces=namespaces
        )
    return saas_file_list.where(env_name=env_name, app_name=app_name)


def get_saasherder_settings(
    query_func: Optional[Callable] = None,
) -> AppInterfaceSettingsV1:
    if not query_func:
        query_func = gql.get_api().query
    if _settings := saasherder_settings_query(query_func).settings:
        return _settings[0]
    raise AppInterfaceSettingsError("settings missing")
