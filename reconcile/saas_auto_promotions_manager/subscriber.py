import hashlib
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Optional

from reconcile.saas_auto_promotions_manager.publisher import (
    DeploymentInfo,
    Publisher,
)

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
    """
    Hold all information about a saas subscriber target.
    Contains logic to determine desired state.
    """

    def __init__(
        self,
        saas_name: str,
        template_name: str,
        ref: str,
        target_file_path: str,
        namespace_file_path: str,
        use_target_config_hash: bool,
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
        self._use_target_config_hash = use_target_config_hash

    def has_diff(self) -> bool:
        current_hashes = {
            el for s in self.config_hashes_by_channel_name.values() for el in s
        }
        # We explicitly only care about subset - we do not care about
        # dangling current hashes - these are checked in saasherder
        # MR validation function.
        desired_hashes_are_in_current_hashes = (
            set(self.desired_hashes) <= current_hashes
        )
        return not (
            desired_hashes_are_in_current_hashes and self.desired_ref == self.ref
        )

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
        # Note: this will be refactored at a later point.
        # https://issues.redhat.com/browse/APPSRE-7516
        if not self._use_target_config_hash:
            # We do not care about config hashes
            return
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

    @staticmethod
    def combined_content_hash(subscribers: Iterable["Subscriber"]) -> str:
        """
        Get a deterministic content hash for the attributes of a collection
        of subscribers. The order of subscribers must not matter for the hash.
        It is important that this is a deterministic operation, because
        SAPM uses this hash to compare the content of MRs.
        """
        sorted_subs = sorted(
            subscribers,
            key=lambda s: (s.target_file_path, s.template_name, s.namespace_file_path),
        )
        m = hashlib.sha256()
        msg = ""
        for sub in sorted_subs:
            sorted_hashes: list[ConfigHash] = sorted(
                sub.desired_hashes,
                key=lambda a: (a.channel, a.parent_saas, a.target_config_hash),
            )
            msg += f"""
            target_file_path: {sub.target_file_path}
            namespace_file_path: {sub.namespace_file_path}
            desired_ref: {sub.desired_ref}
            desired_hashes: {[(h.channel, h.parent_saas, h.target_config_hash) for h in sorted_hashes]}
            """
        m.update(msg.encode("utf-8"))
        return m.hexdigest()[:CONTENT_HASH_LENGTH]
