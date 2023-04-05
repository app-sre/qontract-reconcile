import hashlib
import logging
from dataclasses import dataclass
from typing import Optional

from reconcile.saas_auto_promotions_manager.publisher import Publisher
from reconcile.saas_auto_promotions_manager.utils.deployment_state import DeploymentInfo

CONTENT_HASH_LENGTH = 32


@dataclass
class Channel:
    name: str
    publishers: list[Publisher]


@dataclass(eq=True, frozen=True)
class ConfigHash:
    channel: str
    target_config_hash: str
    parent_saas: str


class Subscriber:
    def __init__(
        self,
        saas_name: str,
        template_name: str,
        ref: str,
        target_file_path: str,
        namespace_file_path: str,
    ):
        self.saas_name = saas_name
        self.template_name = template_name
        self.ref = ref
        self.target_file_path = target_file_path
        self.config_hashes_by_channel_name: dict[str, list[ConfigHash]] = {}
        self.channels: list[Channel] = []
        self.desired_ref = ""
        self.desired_hashes: list[ConfigHash] = []
        self.namespace_file_path = namespace_file_path
        self._content_hash = ""

    def compute_desired_state(self) -> None:
        self._compute_desired_ref()
        self._compute_desired_config_hashes()

    def _validate_deployment(
        self, publisher: Publisher, channel: Channel
    ) -> Optional[DeploymentInfo]:
        deployment_info = publisher.deployment_info_by_channel.get(channel.name)
        if not deployment_info:
            logging.info(
                "[%s] Commit sha %s not found in deployments",
                channel.name,
                publisher.commit_sha,
            )
            return None
        if not deployment_info.success:
            logging.info(
                "[%s] Commit sha %s wasnt successfully deployed",
                channel.name,
                publisher.commit_sha,
            )
            return None
        return deployment_info

    def _compute_desired_ref(self) -> None:
        """
        Compute the desired reference for this subscriber.
        Essentially we are looking at every subscribed channel and check if all the publishers
        have the same new commit sha. If they do not have the same new commit sha or are not
        successfully deployed, then this subscriber is not ready for promotion and we keep
        the current ref.
        """
        new_ref = ""
        for channel in self.channels:
            publisher = channel.publishers[0]
            valid_deployment = self._validate_deployment(
                publisher=publisher, channel=channel
            )
            if not valid_deployment:
                new_ref = ""
                break
            if self.ref != publisher.commit_sha:
                if new_ref and new_ref != publisher.commit_sha:
                    logging.info(
                        "[%s] mismatching commit shas in different subscribed channels (%s != %s) -> not ready for promotion",
                        channel.name,
                        publisher.commit_sha,
                        new_ref,
                    )
                    new_ref = ""
                    break
                new_ref = publisher.commit_sha
        self.desired_ref = new_ref if new_ref else self.ref

    def _compute_desired_config_hashes(self) -> None:
        """
        Compute the desired config hashes for this subscriber.
        Essentially we are looking at every subscribed channel and check for new
        target config hashes in the publishers. For any publisher with a bad
        deployment, we keep the current target config hash.
        """
        for channel in self.channels:
            subscriber_config_hash = None
            if hashes := self.config_hashes_by_channel_name.get(channel.name, []):
                subscriber_config_hash = hashes[0]
            publisher = channel.publishers[0]
            valid_deployment = self._validate_deployment(
                publisher=publisher, channel=channel
            )
            if not valid_deployment:
                # No valid deployment for publisher - lets keep current state
                if subscriber_config_hash:
                    self.desired_hashes.append(subscriber_config_hash)
                else:
                    logging.info(
                        "[%s] Cannot promote target_config_hash because of bad deployment",
                        channel.name,
                    )
            else:
                self.desired_hashes.append(
                    ConfigHash(
                        channel=channel.name,
                        parent_saas=valid_deployment.saas_file,
                        target_config_hash=valid_deployment.target_config_hash,
                    )
                )

    def content_hash(self) -> str:
        """
        Get a content hash for the attributes of this subscriber.
        It is important that this is a deterministic operation, because
        SAPM uses this hash to compare the content of MRs.
        """
        if self._content_hash:
            return self._content_hash
        sorted_hashes: list[ConfigHash] = sorted(
            self.desired_hashes,
            key=lambda a: (a.channel, a.parent_saas, a.target_config_hash),
        )
        m = hashlib.sha256()
        m.update(
            f"""
            target_file_path: {self.target_file_path}
            namespace_file_path: {self.namespace_file_path}
            desired_ref: {self.desired_ref}
            desired_hashes: {[(h.channel, h.parent_saas, h.target_config_hash) for h in sorted_hashes]}
            """.encode(
                "utf-8"
            )
        )
        self._content_hash = m.hexdigest()[:CONTENT_HASH_LENGTH]
        return self._content_hash
