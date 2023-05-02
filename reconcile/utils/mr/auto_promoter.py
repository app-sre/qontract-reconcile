import hashlib
import json
import logging
from collections.abc import (
    Iterable,
    MutableMapping,
)
from dataclasses import (
    asdict,
    dataclass,
)
from typing import (
    Any,
    Sequence,
    Union,
)

from ruamel import yaml

from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.mr.base import MergeRequestBase
from reconcile.utils.mr.labels import AUTO_MERGE
from reconcile.utils.saasherder.interfaces import SaasPromotion
from reconcile.utils.saasherder.models import Promotion

LOG = logging.getLogger(__name__)


@dataclass
class ParentSaasConfigPromotion:
    TYPE = "parent_saas_config"
    parent_saas: str
    target_config_hash: str
    type: str = TYPE


class AutoPromoter(MergeRequestBase):
    name = "auto_promoter"

    def __init__(
        self, promotions: Union[Sequence[SaasPromotion], Sequence[dict[str, Any]]]
    ):
        # !!! Attention !!!
        # AutoPromoter is also initialized with promitions as dict by 'gitlab_mr_sqs_consumer'
        # loaded from SQS message body, therefore self.promotions must be json serializable
        self.promotions = [
            p.dict(by_alias=True) if isinstance(p, SaasPromotion) else p
            for p in promotions
        ]

        # the parent class stores self.promotions (the json serializable one) in self.sqs_msg_data
        super().__init__()
        # create an internal list with Promotion objects out of self.promotions
        self._promotions = [Promotion(**p) for p in self.promotions]
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
    def init_promotion_data(channel: str, promotion: SaasPromotion) -> dict[str, Any]:
        psc = ParentSaasConfigPromotion(
            parent_saas=promotion.saas_file,
            target_config_hash=promotion.target_config_hash,
        )
        return {"channel": channel, "data": [asdict(psc)]}

    @staticmethod
    def process_promotion(
        promotion: SaasPromotion,
        target_promotion: MutableMapping[str, Any],
        target_channels: Iterable[str],
    ) -> bool:
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
                            parent_saas=promotion.saas_file,
                            target_config_hash=promotion.target_config_hash,
                        )
                        if target_psc != promotion_psc:
                            channel_data[i] = asdict(promotion_psc)
                            modified = True

        return modified

    def process_target(
        self, target: MutableMapping[str, Any], promotion: SaasPromotion
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
        if not promotion.publish:
            return target_updated

        channels = [c for c in subscribe if c in promotion.publish]
        if channels:
            # Update REF on target if differs.
            if target["ref"] != promotion.commit_sha:
                target["ref"] = promotion.commit_sha
                target_updated = True

            # Update Promotion data
            modified = self.process_promotion(promotion, target_promotion, channels)

            if modified:
                target_updated = True

        return target_updated

    def process(self, gitlab_cli: GitLabApi) -> None:
        for promotion in self._promotions:
            if not promotion.publish:
                continue
            if not promotion.commit_sha:
                continue
            for saas_file_path in promotion.saas_file_paths or []:
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
                        if self.process_target(target, promotion):
                            saas_file_updated = True

                if saas_file_updated:
                    new_content = "---\n"
                    new_content += yaml.dump(content, Dumper=yaml.RoundTripDumper) or ""
                    msg = f"auto promote {promotion.commit_sha} in {saas_file_path}"
                    gitlab_cli.update_file(
                        branch_name=self.branch,
                        file_path=saas_file_path,
                        commit_message=msg,
                        content=new_content,
                    )
                else:
                    LOG.info(
                        f"commit sha {promotion.commit_sha} has already been "
                        f"promoted to all targets in {content['name']} "
                        f"subscribing to {','.join(promotion.publish)}"
                    )

            for target_path in promotion.target_paths or []:
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
                if self.process_target(content, promotion):
                    new_content = "---\n"
                    new_content += yaml.dump(content, Dumper=yaml.RoundTripDumper)
                    msg = f"auto promote {promotion.commit_sha} in {target_path}"
                    gitlab_cli.update_file(
                        branch_name=self.branch,
                        file_path=target_path,
                        commit_message=msg,
                        content=new_content,
                    )
                else:
                    LOG.info(
                        f"commit sha {promotion.commit_sha} has already been "
                        f"promoted to all targets in {content['name']} "
                        f"subscribing to {','.join(promotion.publish)}"
                    )
