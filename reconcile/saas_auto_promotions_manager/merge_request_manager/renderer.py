from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from jsonpath_ng.exceptions import JsonPathParserError
from jsonpath_ng.ext import parser
from ruamel.yaml import YAML
from ruamel.yaml.compat import StringIO

from reconcile.gql_definitions.common.saas_files import (
    SaasResourceTemplateTargetNamespaceSelectorV1,
)
from reconcile.gql_definitions.fragments.saas_target_namespace import (
    SaasTargetNamespace,
)
from reconcile.saas_auto_promotions_manager.subscriber import Subscriber

PROMOTION_DATA_SEPARATOR = (
    "**SAPM Data - DO NOT MANUALLY CHANGE ANYTHING BELOW THIS LINE**"
)
SAPM_VERSION = "1.0.0"
SAPM_LABEL = "SAPM"
CONTENT_HASH = "content_hash"
CHANNELS_REF = "channels"
VERSION_REF = "sapm_version"
SAPM_DESC = f"""
This is an auto-promotion triggered by app-interface's [saas-auto-promotions-manager](https://github.com/app-sre/qontract-reconcile/tree/master/reconcile/saas_auto_promotions_manager) (SAPM).
The channel(s) mentioned in the MR title had an event.
This MR promotes all subscribers with auto-promotions for these channel(s).

Please **do not remove the {SAPM_LABEL} label** from this MR.

Parts of this description are used by SAPM to manage auto-promotions.
"""


class Renderer:
    """
    This class is only concerned with rendering text for MRs.
    Most logic evolves around ruamel yaml modification.
    This class makes testing for MergeRequestManager easier.

    Note, that this class is very susceptible to schema changes
    as it mainly works on raw dicts.
    """

    def _is_wanted_target(
        self, subscriber: Subscriber, target: Mapping[str, Any]
    ) -> bool:
        namespace_selector = deepcopy(target.get("namespaceSelector"))
        if namespace_selector:
            # We want to fail hard here on missing key - this should not happen
            if "exclude" not in namespace_selector["jsonPathSelectors"]:
                namespace_selector["jsonPathSelectors"]["exclude"] = []
            selector = SaasResourceTemplateTargetNamespaceSelectorV1(
                **namespace_selector
            )
            # Check if the target namespace is addressed by the selector
            return (
                len(
                    get_namespaces_by_selector(
                        namespaces=[subscriber.target_namespace],
                        namespace_selector=selector,
                    )
                )
                == 1
            )
        return target["namespace"]["$ref"] == subscriber.target_namespace.path

    def _find_saas_file_targets(
        self, subscriber: Subscriber, content: dict
    ) -> list[dict]:
        targets: list[dict] = []
        # TODO: better type safety -> catch if schema name changes
        if content["$schema"] == "/app-sre/saas-file-target-1.yml":
            return [content]
        for rt in content["resourceTemplates"]:
            for target in rt["targets"]:
                if not self._is_wanted_target(subscriber=subscriber, target=target):
                    continue
                target_promotion = target.get("promotion")
                if not target_promotion:
                    continue
                if not bool(target_promotion.get("auto", False)):
                    continue
                subscriber_channels = {ch.name for ch in subscriber.channels}
                target_channels = set(target_promotion.get("subscribe", []))
                if subscriber_channels != target_channels:
                    continue
                targets.append(target)
        return targets

    def render_merge_request_content(
        self, subscriber: Subscriber, current_content: str
    ) -> str:
        """
        Note, that this does currently not remove any stale
        promotion data!
        """
        # TODO: make prettier
        # this function is hell - but well tested
        yml = YAML(typ="rt", pure=True)
        yml.preserve_quotes = True
        # Lets prevent line wraps
        yml.width = 4096
        content = yml.load(current_content)
        targets = self._find_saas_file_targets(subscriber=subscriber, content=content)
        for target in targets:
            target["ref"] = subscriber.desired_ref
            cur_promotion_data = target["promotion"].get("promotion_data", [])
            for desired_config_hash in subscriber.desired_hashes:
                applied_desired_hash = False
                for cur_hash in cur_promotion_data:
                    if cur_hash["channel"] != desired_config_hash.channel:
                        continue
                    data = cur_hash.get("data", [])
                    for d in data:
                        if d.get("parent_saas") != desired_config_hash.parent_saas:
                            continue
                        d["target_config_hash"] = desired_config_hash.target_config_hash
                        applied_desired_hash = True
                if not applied_desired_hash:
                    # This data block is not part of the promotion data yet -> add it
                    cur_promotion_data.append(
                        {
                            "channel": desired_config_hash.channel,
                            "data": [
                                {
                                    "parent_saas": desired_config_hash.parent_saas,
                                    "target_config_hash": desired_config_hash.target_config_hash,
                                    "type": "parent_saas_config",
                                }
                            ],
                        }
                    )
            if cur_promotion_data:
                target["promotion"]["promotion_data"] = cur_promotion_data
        new_content = "---\n"
        with StringIO() as stream:
            yml.dump(content, stream)
            new_content += stream.getvalue() or ""
        return new_content

    def render_description(self, content_hash: str, channels: str) -> str:
        return f"""
{SAPM_DESC}

{PROMOTION_DATA_SEPARATOR}

{CHANNELS_REF}: {channels}

{CONTENT_HASH}: {content_hash}

{VERSION_REF}: {SAPM_VERSION}
        """

    def render_title(self, channels: str) -> str:
        return f"[auto-promotion] event for channel(s) {channels}"


def get_namespaces_by_selector(
    namespaces: list[SaasTargetNamespace],
    namespace_selector: SaasResourceTemplateTargetNamespaceSelectorV1,
) -> list[SaasTargetNamespace]:
    """
    # TODO: for whatever reason tox fails to import this from saas_files.
    Interestingly it works outside of tox, but to get going we simply
    copy the function here - very bad style but works for now

    Copy of reconcile.typed_queries.saas_files.get_namespaces_by_selector
    """

    # json representation of all the namespaces to filter on
    # remove all the None values to simplify the jsonpath expressions
    namespaces_as_dict = {
        "namespace": [ns.dict(by_alias=True, exclude_none=True) for ns in namespaces]
    }

    def _get_namespace_by_cluster_and_name(
        cluster_name: str, name: str
    ) -> SaasTargetNamespace:
        for ns in namespaces:
            if ns.cluster.name == cluster_name and ns.name == name:
                return ns
        # this should never ever happen - just make mypy happy
        raise RuntimeError(f"namespace '{name}' not found in cluster '{cluster_name}'")

    filtered_namespaces: dict[str, Any] = {}

    try:
        for include in namespace_selector.json_path_selectors.include:
            for match in parser.parse(include).find(namespaces_as_dict):
                cluster_name = match.value["cluster"]["name"]
                ns_name = match.value["name"]
                filtered_namespaces[
                    f"{cluster_name}-{ns_name}"
                ] = _get_namespace_by_cluster_and_name(cluster_name, ns_name)
    except JsonPathParserError as e:
        raise RuntimeError(
            f"Invalid jsonpath expression in namespaceSelector '{include}' :{e}"
        )

    try:
        for exclude in namespace_selector.json_path_selectors.exclude or []:
            for match in parser.parse(exclude).find(namespaces_as_dict):
                cluster_name = match.value["cluster"]["name"]
                ns_name = match.value["name"]
                filtered_namespaces.pop(f"{cluster_name}-{ns_name}", None)
    except JsonPathParserError as e:
        raise RuntimeError(
            f"Invalid jsonpath expression in namespaceSelector '{exclude}' :{e}"
        )
    return list(filtered_namespaces.values())
