import logging
from collections.abc import Iterable

from reconcile.gql_definitions.common.saas_files import ParentSaasPromotionV1
from reconcile.saas_auto_promotions_manager.publisher import Publisher
from reconcile.saas_auto_promotions_manager.subscriber import (
    Channel,
    ConfigHash,
    Subscriber,
)
from reconcile.typed_queries.saas_files import SaasFile


class SaasFileInventoryError(Exception):
    pass


class SaasFilesInventory:
    """
    An abstraction around a collection SaaS files. This helps to separate
    the query model from the business logic model. Further, it helps to
    retrieve information in different formats around SaaS files.
    Note, that all this is merely model transformation - there are no external
    dependencies involved. Publishers, Subscribers and Channels have a n<->n<->n relationship.
    This basically spans a directed graph, with subscribers as the root.
    """

    def __init__(self, saas_files: Iterable[SaasFile]):
        self._saas_files = saas_files
        self._channels_by_name: dict[str, Channel] = {}
        self.subscribers: list[Subscriber] = []
        self.publishers: list[Publisher] = []
        self._assemble_subscribers_with_auto_promotions()
        self._assemble_publishers()
        self._remove_unsupported()

    def _assemble_publishers(self) -> None:
        for saas_file in self._saas_files:
            for resource_template in saas_file.resource_templates:
                for target in resource_template.targets:
                    if not target.promotion:
                        continue
                    auth_code = (
                        saas_file.authentication.code
                        if saas_file.authentication
                        else None
                    )
                    publisher = Publisher(
                        ref=target.ref,
                        uid=target.uid(
                            parent_saas_file_name=saas_file.name,
                            parent_resource_template_name=resource_template.name,
                        ),
                        repo_url=resource_template.url,
                        auth_code=auth_code,
                    )
                    has_subscriber = False
                    for publish_channel in target.promotion.publish or []:
                        if publish_channel not in self._channels_by_name:
                            continue
                        has_subscriber = True
                        publisher.channels.add(
                            self._channels_by_name[publish_channel].name
                        )
                        self._channels_by_name[publish_channel].publishers.append(
                            publisher
                        )
                    if has_subscriber:
                        self.publishers.append(publisher)

    def _assemble_subscribers_with_auto_promotions(self) -> None:
        for saas_file in self._saas_files:
            for resource_template in saas_file.resource_templates:
                for target in resource_template.targets:
                    file_path = target.path if target.path else saas_file.path
                    if not target.promotion:
                        continue
                    if not target.promotion.auto:
                        continue
                    subscriber = Subscriber(
                        saas_name=saas_file.name,
                        template_name=resource_template.name,
                        target_file_path=file_path,
                        ref=target.ref,
                        target_namespace=target.namespace,
                        # Note: this will be refactored at a later point.
                        # https://issues.redhat.com/browse/APPSRE-7516
                        use_target_config_hash=bool(saas_file.publish_job_logs),
                    )
                    self.subscribers.append(subscriber)
                    for prom_data in target.promotion.promotion_data or []:
                        if not prom_data.channel:
                            continue
                        for data in prom_data.data or []:
                            if not isinstance(data, ParentSaasPromotionV1):
                                continue
                            if not (data.target_config_hash and data.parent_saas):
                                raise SaasFileInventoryError(
                                    f"ParentSaasPromotionV1 data without target_config_hash and/or parent_saas: {saas_file}"
                                )
                            if (
                                prom_data.channel
                                not in subscriber.config_hashes_by_channel_name
                            ):
                                subscriber.config_hashes_by_channel_name[
                                    prom_data.channel
                                ] = []
                            subscriber.config_hashes_by_channel_name[
                                prom_data.channel
                            ].append(
                                ConfigHash(
                                    channel=prom_data.channel,
                                    target_config_hash=data.target_config_hash,
                                    parent_saas=data.parent_saas,
                                )
                            )

                    for subscribe_channel in target.promotion.subscribe or []:
                        if subscribe_channel not in self._channels_by_name:
                            self._channels_by_name[subscribe_channel] = Channel(
                                name=subscribe_channel,
                                publishers=[],
                            )
                        subscriber.channels.append(
                            self._channels_by_name[subscribe_channel]
                        )

    def _remove_unsupported(self) -> None:
        """
        Lets remove subscribers from which we know we do not support them and log an error.
        Ideally this will never happen and is validated by a saas sanity check on MR level.
        """
        supported_subscribers: list[Subscriber] = []
        for subscriber in self.subscribers:
            is_supported = True
            for channel in subscriber.channels:
                if not channel.publishers:
                    logging.error(
                        "[%s] There must be at least one publisher per channel.",
                        channel.name,
                    )
                    is_supported = False
                    break
            if is_supported:
                supported_subscribers.append(subscriber)
        self.subscribers = supported_subscribers
        # Ideally we also remove the publishers that are left w/o subscriber.
        # But lets solve APPSRE-7414 - then it wont be necessary in the first place.
