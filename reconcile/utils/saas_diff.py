from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from reconcile.gql_definitions.common.saas_files import (
    DeployResourcesV1,
    SaasResourceTemplateTargetUpstreamV1,
)
from reconcile.gql_definitions.fragments.vault_secret import VaultSecret

if TYPE_CHECKING:
    from collections.abc import Iterable

    from reconcile.typed_queries.saas_files import SaasFile


class Definition(BaseModel):
    managed_resource_types: list[str]
    image_patterns: list[str]
    use_channel_in_image_tag: bool


class State(BaseModel):
    saas_file_path: str
    saas_file_name: str
    saas_file_deploy_resources: DeployResourcesV1 | None = None
    resource_template_name: str
    cluster: str
    namespace: str
    environment: str
    url: str
    ref: str
    parameters: dict[str, Any]
    secret_parameters: dict[str, VaultSecret]
    saas_file_definitions: Definition
    upstream: SaasResourceTemplateTargetUpstreamV1 | None = None
    disable: bool | None = None
    delete: bool | None = None
    target_path: str | None = None


def collect_state(saas_files: list[SaasFile]) -> list[State]:
    state = []
    for saas_file in saas_files:
        definitions = Definition(
            managed_resource_types=saas_file.managed_resource_types,
            image_patterns=saas_file.image_patterns,
            use_channel_in_image_tag=saas_file.use_channel_in_image_tag or False,
        )

        for resource_template in saas_file.resource_templates:
            for target in resource_template.targets:
                parameters: dict[str, Any] = {}
                parameters.update(saas_file.parameters or {})
                parameters.update(resource_template.parameters or {})
                parameters.update(target.parameters or {})
                secret_parameters: dict[str, VaultSecret] = {}
                secret_parameters.update({
                    s.name: s.secret for s in saas_file.secret_parameters or []
                })
                secret_parameters.update({
                    s.name: s.secret for s in resource_template.secret_parameters or []
                })
                secret_parameters.update({
                    s.name: s.secret for s in target.secret_parameters or []
                })
                state.append(
                    State(
                        saas_file_path=saas_file.path,
                        saas_file_name=saas_file.name,
                        saas_file_deploy_resources=saas_file.deploy_resources,
                        resource_template_name=resource_template.name,
                        cluster=target.namespace.cluster.name,
                        namespace=target.namespace.name,
                        environment=target.namespace.environment.name,
                        url=resource_template.url,
                        ref=target.ref,
                        parameters=parameters,
                        secret_parameters=secret_parameters,
                        saas_file_definitions=definitions,
                        upstream=target.upstream,
                        disable=target.disable,
                        delete=target.delete,
                        target_path=target.path,
                    )
                )
    return state


def find_ref_diffs(
    current_state: Iterable[State],
    desired_state: Iterable[State],
    changed_paths: Iterable[str],
) -> list[tuple[State, State]]:
    """
    Match desired-state targets against current-state targets by
    (saas_file_name, resource_template_name, environment, cluster,
    namespace), skipping targets whose saas file is not part of
    changed_paths and targets whose ref did not actually change.

    Returns (desired, current) State pairs for each detected ref change.
    Shared by openshift_saas_deploy_change_tester.collect_compare_diffs and
    rcs_analyze_trigger.collect_component_diffs so a fix to the matching
    rule only has to be made in one place.
    """
    matches: list[tuple[State, State]] = []
    for d in desired_state:
        # check if this diff was actually changed in the current MR
        changed_path_matches = [
            c for c in changed_paths if c.endswith(d.saas_file_path)
        ]
        if not changed_path_matches:
            # this diff was found in the graphql endpoint comparison
            # but is not a part of the changed paths.
            # the only known case for this currently is if a previous MR
            # that changes another saas file was merged but is not yet
            # reflected in the baseline graphql endpoint.
            # https://issues.redhat.com/browse/APPSRE-3029
            logging.debug(f"Diff not found in changed paths, skipping: {d!s}")
            continue
        for c in current_state:
            if d.saas_file_name != c.saas_file_name:
                continue
            if d.resource_template_name != c.resource_template_name:
                continue
            if d.environment != c.environment:
                continue
            if d.cluster != c.cluster:
                continue
            if d.namespace != c.namespace:
                continue
            if d.ref == c.ref:
                continue
            matches.append((d, c))
    return matches
