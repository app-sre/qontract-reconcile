from ruamel.yaml import YAML
from ruamel.yaml.compat import StringIO

from reconcile.saas_auto_promotions_manager.subscriber import Subscriber

PROMOTION_DATA_SEPARATOR = (
    "**SAPM Data - DO NOT MANUALLY CHANGE ANYTHING BELOW THIS LINE**"
)
CONTENT_HASH = "content_hash"
NAMESPACE_REF = "namespace_ref"
FILE_PATH = "file_path"
SAPM_DESC = """
This is an auto-promotion triggered by app-interface.
"""


class Renderer:
    """
    This class makes testing for MergeRequestManager easier.
    """

    def _find_saas_file_target(self, subscriber: Subscriber, content: dict) -> dict:
        # TODO: better type safety -> catch if schema name changes
        if content["$schema"] == "/app-sre/saas-file-target-1.yml":
            return content
        for rt in content["resourceTemplates"]:
            for target in rt["targets"]:
                if target["namespace"]["$ref"] != subscriber.namespace_file_path:
                    continue
                target_promotion = target.get("promotion")
                if not target_promotion:
                    continue
                return target
        # TODO
        raise RuntimeError("Target for promotion could not be found in file")

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
        content = yml.load(current_content)
        target = self._find_saas_file_target(subscriber=subscriber, content=content)
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
        target["promotion"]["promotion_data"] = cur_promotion_data
        new_content = "---\n"
        with StringIO() as stream:
            yml.dump(content, stream)
            new_content += stream.getvalue() or ""
        return new_content

    def render_description(self, subscriber: Subscriber) -> str:
        return f"""
    {SAPM_DESC}

    {PROMOTION_DATA_SEPARATOR}

    {FILE_PATH}: {subscriber.target_file_path}
    {NAMESPACE_REF}: {subscriber.namespace_file_path}
    {CONTENT_HASH}: {subscriber.content_hash()}
        """

    def render_title(self, subscriber: Subscriber) -> str:
        return "[SAPM] auto-promotion"
