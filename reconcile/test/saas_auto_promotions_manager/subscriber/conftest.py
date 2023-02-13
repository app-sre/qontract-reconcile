from collections import defaultdict
from collections.abc import (
    Callable,
    Iterable,
    Mapping,
)
from typing import Any

import pytest

from reconcile.saas_auto_promotions_manager.publisher import Publisher
from reconcile.saas_auto_promotions_manager.subscriber import (
    Channel,
    ConfigHash,
    Subscriber,
)
from reconcile.saas_auto_promotions_manager.utils.deployment_state import DeploymentInfo

from .data_keys import (
    CHANNELS,
    CONFIG_HASH,
    CUR_CONFIG_HASHES,
    CUR_SUBSCRIBER_REF,
    REAL_WORLD_SHA,
    SUCCESSFUL_DEPLOYMENT,
)


@pytest.fixture
def config_hashes_builder() -> Callable[
    [Iterable[tuple[str, str, str]]], list[ConfigHash]
]:
    def builder(data: Iterable[tuple[str, str, str]]) -> list[ConfigHash]:
        return [
            ConfigHash(
                channel=d[0],
                parent_saas=d[1],
                target_config_hash=d[2],
            )
            for d in data
        ]

    return builder


@pytest.fixture
def subscriber_builder() -> Callable[[Mapping[str, Any]], Subscriber]:
    def builder(data: Mapping[str, Any]) -> Subscriber:
        channels: list[Channel] = []
        for channel_name, channel_data in data.get(CHANNELS, {}).items():
            channel = Channel(name=channel_name, publishers=[])
            for publisher_name, publisher_data in channel_data.items():
                publisher = Publisher(
                    ref="",
                    repo_url="",
                    auth_code=None,
                )
                publisher.commit_sha = publisher_data[REAL_WORLD_SHA]
                publisher.deployment_info_by_channel[channel_name] = DeploymentInfo(
                    success=publisher_data.get(SUCCESSFUL_DEPLOYMENT, True),
                    target_config_hash=publisher_data.get(CONFIG_HASH, ""),
                    saas_file=publisher_name,
                )
                channel.publishers.append(publisher)
            channels.append(channel)
        cur_config_hashes_by_channel: dict[str, list[ConfigHash]] = defaultdict(list)
        for cur_config_hash in data[CUR_CONFIG_HASHES]:
            cur_config_hashes_by_channel[cur_config_hash[0]].append(
                ConfigHash(
                    channel=cur_config_hash[0],
                    parent_saas=cur_config_hash[1],
                    target_config_hash=cur_config_hash[2],
                )
            )
        subscriber = Subscriber(
            namespace_file_path="",
            ref=data[CUR_SUBSCRIBER_REF],
            saas_name="",
            target_file_path="",
            template_name="",
        )
        subscriber.channels = channels
        subscriber.config_hashes_by_channel_name = cur_config_hashes_by_channel
        return subscriber

    return builder
