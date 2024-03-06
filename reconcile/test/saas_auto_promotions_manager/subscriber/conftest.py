from collections import defaultdict
from collections.abc import (
    Callable,
    Mapping,
)
from typing import Any

import pytest

from reconcile.gql_definitions.fragments.saas_target_namespace import (
    SaasTargetNamespace,
)
from reconcile.saas_auto_promotions_manager.publisher import (
    DeploymentInfo,
    Publisher,
)
from reconcile.saas_auto_promotions_manager.subscriber import (
    Channel,
    ConfigHash,
    Subscriber,
)

from .data_keys import (
    CHANNELS,
    CONFIG_HASH,
    CUR_CONFIG_HASHES,
    CUR_SUBSCRIBER_REF,
    DESIRED_REF,
    DESIRED_TARGET_HASHES,
    NAMESPACE,
    REAL_WORLD_SHA,
    SUCCESSFUL_DEPLOYMENT,
    TARGET_FILE_PATH,
    USE_TARGET_CONFIG_HASH,
)


@pytest.fixture
def subscriber_builder(
    saas_target_namespace_builder: Callable[..., SaasTargetNamespace],
) -> Callable[[Mapping[str, Any]], Subscriber]:
    def builder(data: Mapping[str, Any]) -> Subscriber:
        channels: list[Channel] = []
        for channel_name, channel_data in data.get(CHANNELS, {}).items():
            channel = Channel(name=channel_name, publishers=[])
            for publisher_name, publisher_data in channel_data.items():
                publisher = Publisher(
                    ref="",
                    uid="",
                    repo_url="",
                    cluster_name="",
                    namespace_name="",
                    saas_name="",
                    saas_file_path="",
                    resource_template_name="",
                    target_name=None,
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
        for cur_config_hash in data.get(CUR_CONFIG_HASHES, []):
            cur_config_hashes_by_channel[cur_config_hash.channel].append(
                cur_config_hash
            )
        subscriber = Subscriber(
            target_namespace=saas_target_namespace_builder(data.get(NAMESPACE, {})),
            ref=data.get(CUR_SUBSCRIBER_REF, ""),
            saas_name="",
            target_file_path=data.get(TARGET_FILE_PATH, ""),
            template_name="",
            use_target_config_hash=data.get(USE_TARGET_CONFIG_HASH, True),
        )
        subscriber.channels = channels
        subscriber.config_hashes_by_channel_name = cur_config_hashes_by_channel
        subscriber.desired_ref = data.get(DESIRED_REF, "")
        subscriber.desired_hashes = data.get(DESIRED_TARGET_HASHES, [])
        return subscriber

    return builder
