from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from reconcile.gql_definitions.common.app_interface_settings import (
    AppInterfaceDependencyMappingV1,
    DependencyV1,
)
from reconcile.gql_definitions.service_dependencies.jenkins_instance_fragment import (
    ServiceDependenciesJenkinsInstance,
)
from reconcile.gql_definitions.service_dependencies.service_dependencies import (
    AppCodeComponentsV1,
    AppQuayReposV1,
    AppV1,
    JenkinsConfigV1,
    NamespaceExternalResourceV1,
    NamespaceV1,
    PipelinesProviderV1,
    QuayInstanceV1,
    QuayOrgV1,
    SaasFileV2,
    SaasResourceTemplateTargetUpstreamV1,
    SaasResourceTemplateTargetV2,
    SaasResourceTemplateV2,
    ServiceDependenciesQueryData,
)
from reconcile.gql_definitions.service_dependencies.service_dependencies import (
    DependencyV1 as AppDependencyV1,
)
from reconcile.service_dependencies import (
    QONTRACT_INTEGRATION,
    get_dependency_names,
    get_desired_dependency_names,
    run,
)

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


@pytest.fixture
def dependency_map() -> list[AppInterfaceDependencyMappingV1]:
    return [
        AppInterfaceDependencyMappingV1(
            type="github",
            services=[DependencyV1(name="github")],
        ),
        AppInterfaceDependencyMappingV1(
            type="openshift",
            services=[
                DependencyV1(name="openshift"),
                DependencyV1(name="openshift-vault"),
            ],
        ),
    ]


def test_get_dependency_names_returns_service_names_for_matching_type(
    dependency_map: list[AppInterfaceDependencyMappingV1],
) -> None:
    assert get_dependency_names(dependency_map, "openshift") == [
        "openshift",
        "openshift-vault",
    ]


def test_get_dependency_names_returns_service_names_for_single_service_type(
    dependency_map: list[AppInterfaceDependencyMappingV1],
) -> None:
    assert get_dependency_names(dependency_map, "github") == ["github"]


def test_get_dependency_names_returns_empty_list_for_unknown_type(
    dependency_map: list[AppInterfaceDependencyMappingV1],
) -> None:
    assert get_dependency_names(dependency_map, "quay") == []


def _build_app(dependencies: list[str] | None) -> AppV1:
    return AppV1(
        name="an-app",
        dependencies=[AppDependencyV1(name=d) for d in dependencies]
        if dependencies is not None
        else None,
        codeComponents=[AppCodeComponentsV1(url="https://github.com/org/repo")],
        jenkinsConfigs=[
            JenkinsConfigV1(
                instance=ServiceDependenciesJenkinsInstance(name="jenkins-instance")
            )
        ],
        saasFiles=[
            SaasFileV2(
                pipelinesProvider=PipelinesProviderV1(provider="tekton"),
                resourceTemplates=[
                    SaasResourceTemplateV2(
                        targets=[
                            SaasResourceTemplateTargetV2(
                                upstream=SaasResourceTemplateTargetUpstreamV1(
                                    instance=ServiceDependenciesJenkinsInstance(
                                        name="ci-ext"
                                    )
                                )
                            )
                        ]
                    )
                ],
            )
        ],
        quayRepos=[
            AppQuayReposV1(
                org=QuayOrgV1(
                    name="an-org", instance=QuayInstanceV1(name="quay-instance")
                )
            )
        ],
        namespaces=[
            NamespaceV1(
                managedExternalResources=True,
                externalResources=[NamespaceExternalResourceV1(provider="aws")],
            )
        ],
    )


@pytest.fixture
def full_dependency_map() -> list[AppInterfaceDependencyMappingV1]:
    return [
        AppInterfaceDependencyMappingV1(
            type="github", services=[DependencyV1(name="github")]
        ),
        AppInterfaceDependencyMappingV1(
            type="jenkins-instance", services=[DependencyV1(name="jenkins-instance")]
        ),
        AppInterfaceDependencyMappingV1(
            type="openshift", services=[DependencyV1(name="openshift")]
        ),
        AppInterfaceDependencyMappingV1(
            type="ci-ext", services=[DependencyV1(name="ci-ext")]
        ),
        AppInterfaceDependencyMappingV1(
            type="quay", services=[DependencyV1(name="quay")]
        ),
        AppInterfaceDependencyMappingV1(
            type="aws", services=[DependencyV1(name="aws")]
        ),
    ]


def test_get_desired_dependency_names_resolves_every_dependency_category(
    full_dependency_map: list[AppInterfaceDependencyMappingV1],
) -> None:
    app = _build_app(dependencies=[])

    assert get_desired_dependency_names(app, full_dependency_map) == {
        "github",
        "jenkins-instance",
        "openshift",
        "ci-ext",
        "quay",
        "aws",
    }


def test_run_reports_missing_dependencies(
    mocker: MockerFixture,
    full_dependency_map: list[AppInterfaceDependencyMappingV1],
) -> None:
    mocker.patch("reconcile.service_dependencies.gql.get_api")
    mocker.patch(
        "reconcile.service_dependencies.get_app_interface_settings",
        return_value=mocker.Mock(dependencies=full_dependency_map),
    )
    mocker.patch(
        "reconcile.service_dependencies.service_dependencies.query",
        return_value=ServiceDependenciesQueryData(apps=[_build_app(dependencies=[])]),
    )

    with pytest.raises(SystemExit) as exc_info:
        run(dry_run=True)

    assert exc_info.value.code == 1


def test_run_succeeds_when_all_dependencies_are_declared(
    mocker: MockerFixture,
    full_dependency_map: list[AppInterfaceDependencyMappingV1],
) -> None:
    mocker.patch("reconcile.service_dependencies.gql.get_api")
    mocker.patch(
        "reconcile.service_dependencies.get_app_interface_settings",
        return_value=mocker.Mock(dependencies=full_dependency_map),
    )
    mocker.patch(
        "reconcile.service_dependencies.service_dependencies.query",
        return_value=ServiceDependenciesQueryData(
            apps=[
                _build_app(
                    dependencies=[
                        "github",
                        "jenkins-instance",
                        "openshift",
                        "ci-ext",
                        "quay",
                        "aws",
                    ]
                )
            ]
        ),
    )

    run(dry_run=True)


def test_qontract_integration_name() -> None:
    assert QONTRACT_INTEGRATION == "service-dependencies"
