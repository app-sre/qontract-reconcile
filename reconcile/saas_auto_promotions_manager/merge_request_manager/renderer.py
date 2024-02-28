import hashlib
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from jsonpath_ng.exceptions import JsonPathParserError
from jsonpath_ng.ext import parser
from ruamel.yaml.compat import StringIO

from reconcile.gql_definitions.common.saas_files import (
    SaasResourceTemplateTargetNamespaceSelectorV1,
)
from reconcile.gql_definitions.fragments.saas_target_namespace import (
    SaasTargetNamespace,
)
from reconcile.saas_auto_promotions_manager.subscriber import Subscriber
from reconcile.utils.ruamel import create_ruamel_instance

PROMOTION_DATA_SEPARATOR = (
    "**SAPM Data - DO NOT MANUALLY CHANGE ANYTHING BELOW THIS LINE**"
)
SAPM_VERSION = "2.1.3"
CONTENT_HASHES = "content_hashes"
CHANNELS_REF = "channels"
IS_BATCHABLE = "is_batchable"
VERSION_REF = "sapm_version"


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
            return is_namespace_addressed_by_selector(
                namespace=subscriber.target_namespace,
                namespace_selector=selector,
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
        yml = create_ruamel_instance(pure=True)
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
                    cur_promotion_data.append({
                        "channel": desired_config_hash.channel,
                        "data": [
                            {
                                "parent_saas": desired_config_hash.parent_saas,
                                "target_config_hash": desired_config_hash.target_config_hash,
                                "type": "parent_saas_config",
                            }
                        ],
                    })
            if cur_promotion_data:
                target["promotion"]["promotion_data"] = cur_promotion_data
        new_content = "---\n"
        with StringIO() as stream:
            yml.dump(content, stream)
            new_content += stream.getvalue() or ""
        return new_content

    def render_description(
        self, message: str, content_hashes: str, channels: str, is_batchable: bool
    ) -> str:
        return f"""
{message}

{PROMOTION_DATA_SEPARATOR}

{CHANNELS_REF}: {channels}

{CONTENT_HASHES}: {content_hashes}

{IS_BATCHABLE}: {is_batchable}

{VERSION_REF}: {SAPM_VERSION}
        """

    def render_title(
        self, is_draft: bool, canary: bool, channels: str, batch_size: int
    ) -> str:
        canary_suffix = "Canary" if canary else ""
        content = f"[SAPM{canary_suffix}] auto-promotion ID {int(hashlib.sha256(channels.encode('utf-8')).hexdigest(), 16) % 10**8} - batch size: {batch_size}"
        if is_draft:
            return f"Draft: {content}"
        return content


def _parse_expression(expression: str) -> Any:
    try:
        return parser.parse(expression)
    except JsonPathParserError as e:
        raise RuntimeError(
            f"Invalid jsonpath expression in namespaceSelector '{expression}' :{e}"
        )


def is_namespace_addressed_by_selector(
    namespace: SaasTargetNamespace,
    namespace_selector: SaasResourceTemplateTargetNamespaceSelectorV1,
) -> bool:
    # json representation of namespace to filter on
    # remove all the None values to simplify the jsonpath expressions
    namespace_as_dict = {
        "namespace": [namespace.dict(by_alias=True, exclude_none=True)]
    }

    do_include = any(
        _parse_expression(include).find(namespace_as_dict)
        for include in namespace_selector.json_path_selectors.include or []
    )

    do_exclude = any(
        _parse_expression(exclude).find(namespace_as_dict)
        for exclude in namespace_selector.json_path_selectors.exclude or []
    )

    return do_include and not do_exclude
