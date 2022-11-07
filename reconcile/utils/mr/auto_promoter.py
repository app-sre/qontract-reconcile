import logging
import json
import hashlib
from typing import Any, Dict, Mapping, MutableMapping
from dataclasses import dataclass
from dataclasses import asdict
from ruamel import yaml

from reconcile.utils.mr.base import MergeRequestBase
from reconcile.utils.mr.labels import AUTO_MERGE

LOG = logging.getLogger(__name__)

TARGET_CONFIG_HASH = "target_config_hash"


@dataclass
class ParentSaasConfigPromotion:
    TYPE = "parent_saas_config"
    parent_saas: str
    target_config_hash: str
    type: str = TYPE


class AutoPromoter(MergeRequestBase):
    name = "auto_promoter"

    def __init__(self, promotions):
        self.promotions = promotions
        super().__init__()

        self.labels = [AUTO_MERGE]

    @property
    def title(self) -> str:
        """
        to make the MR title unique, add a sha256sum of the promotions to it
        TODO: while adding a digest ensures uniqueness, this title is
              still not very descriptive
        """
        m = hashlib.sha256()
        m.update(json.dumps(self.promotions, sort_keys=True).encode("utf-8"))
        digest = m.hexdigest()[:6]
        return f"[{self.name}] openshift-saas-deploy automated " f"promotion {digest}"

    @property
    def description(self) -> str:
        return "openshift-saas-deploy automated promotion"

    @staticmethod
    def init_promotion_data(
        channel: str, promotion: Mapping[str, Any]
    ) -> Dict[str, Any]:
        psc = ParentSaasConfigPromotion(
            parent_saas=promotion["saas_file"],
            target_config_hash=promotion[TARGET_CONFIG_HASH],
        )
        return {"channel": channel, "data": [asdict(psc)]}

    @staticmethod
    def process_promotion(promotion, target_promotion, target_channels):

        # Existent subscribe data channel data
        promotion_data = {
            v["channel"]: v["data"]
            for v in target_promotion.get("promotion_data", [])
            if v["channel"] in target_channels
        }

        if not promotion_data:
            target_promotion["promotion_data"] = []

        modified = False
        for channel in target_channels:
            channel_data = promotion_data.get(channel)
            if channel_data is None:
                channel_data = AutoPromoter.init_promotion_data(channel, promotion)
                target_promotion["promotion_data"].append(channel_data)
                modified = True
            else:
                for i, item in enumerate(channel_data):
                    if item["type"] == ParentSaasConfigPromotion.TYPE:
                        target_psc = ParentSaasConfigPromotion(**item)
                        promotion_psc = ParentSaasConfigPromotion(
                            parent_saas=promotion["saas_file"],
                            target_config_hash=promotion[TARGET_CONFIG_HASH],
                        )
                        if target_psc != promotion_psc:
                            channel_data[i] = asdict(promotion_psc)
                            modified = True

            return modified

    def process_target(
        self,
        target: MutableMapping[str, Any],
        promotion_item: Mapping[str, Any],
        commit_sha: str,
    ) -> bool:
        target_updated = False
        target_promotion = target.get("promotion")
        if not target_promotion:
            return target_updated
        target_auto = target_promotion.get("auto")
        if not target_auto:
            return target_updated
        subscribe = target_promotion.get("subscribe")
        if not subscribe:
            return target_updated

        channels = [c for c in subscribe if c in promotion_item["publish"]]
        if len(channels) > 0:
            # Update REF on target if differs.
            if target["ref"] != commit_sha:
                target["ref"] = commit_sha
                target_updated = True

            # Update Promotion data
            modified = self.process_promotion(
                promotion_item, target_promotion, channels
            )

            if modified:
                target_updated = True

        return target_updated

    def process(self, gitlab_cli):
        for item in self.promotions:
            saas_file_paths = item.get("saas_file_paths") or []
            target_paths = item.get("target_paths") or []
            if not (saas_file_paths or target_paths):
                continue
            publish = item.get("publish")
            if not publish:
                continue
            commit_sha = item.get("commit_sha")
            if not commit_sha:
                continue
            for saas_file_path in saas_file_paths:
                saas_file_updated = False
                try:
                    # This will only work with gitlab cli, not with SQS
                    # this method is only triggered by gitlab_sqs_consumer
                    # not by openshift_saas_deploy
                    raw_file = gitlab_cli.project.files.get(
                        file_path=saas_file_path, ref=self.branch
                    )
                except Exception as e:
                    logging.error(e)

                content = yaml.load(raw_file.decode(), Loader=yaml.RoundTripLoader)

                for rt in content["resourceTemplates"]:
                    for target in rt["targets"]:
                        if self.process_target(target, item, commit_sha):
                            saas_file_updated = True

                if saas_file_updated:
                    new_content = "---\n"
                    new_content += yaml.dump(content, Dumper=yaml.RoundTripDumper)
                    msg = f"auto promote {commit_sha} in {saas_file_path}"
                    gitlab_cli.update_file(
                        branch_name=self.branch,
                        file_path=saas_file_path,
                        commit_message=msg,
                        content=new_content,
                    )
                else:
                    LOG.info(
                        f"commit sha {commit_sha} has already been "
                        f"promoted to all targets in {content['name']} "
                        f"subscribing to {','.join(item['publish'])}"
                    )

            for target_path in target_paths:
                try:
                    # This will only work with gitlab cli, not with SQS
                    # this method is only triggered by gitlab_sqs_consumer
                    # not by openshift_saas_deploy
                    raw_file = gitlab_cli.project.files.get(
                        file_path=target_path, ref=self.branch
                    )
                except Exception as e:
                    logging.error(e)

                content = yaml.load(raw_file.decode(), Loader=yaml.RoundTripLoader)
                if self.process_target(content, item, commit_sha):
                    new_content = "---\n"
                    new_content += yaml.dump(content, Dumper=yaml.RoundTripDumper)
                    msg = f"auto promote {commit_sha} in {target_path}"
                    gitlab_cli.update_file(
                        branch_name=self.branch,
                        file_path=target_path,
                        commit_message=msg,
                        content=new_content,
                    )
                else:
                    LOG.info(
                        f"commit sha {commit_sha} has already been "
                        f"promoted to all targets in {content['name']} "
                        f"subscribing to {','.join(item['publish'])}"
                    )
