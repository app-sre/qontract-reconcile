from collections import defaultdict
from collections.abc import (
    Callable,
    Iterable,
    Mapping,
    MutableMapping,
)
from datetime import UTC, datetime
from typing import Any
from unittest.mock import (
    MagicMock,
    create_autospec,
)

import pytest

from reconcile.gql_definitions.fragments.saas_target_namespace import (
    SaasTargetNamespace,
)
from reconcile.saas_auto_promotions_manager.publisher import DeploymentInfo, Publisher
from reconcile.saas_auto_promotions_manager.subscriber import (
    Channel,
    ConfigHash,
    Subscriber,
)
from reconcile.typed_queries.saas_files import SaasFile
from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.promotion_state import (
    PromotionData,
    PromotionState,
)
from reconcile.utils.vcs import VCS


@pytest.fixture
def saas_files_builder(
    gql_class_factory: Callable[[type[SaasFile], Mapping], SaasFile],
) -> Callable[[Iterable[MutableMapping]], list[SaasFile]]:
    def builder(data: Iterable[MutableMapping]) -> list[SaasFile]:
        for d in data:
            if "app" not in d:
                d["app"] = {}
            if "pipelinesProvider" not in d:
                d["pipelinesProvider"] = {}
            if "managedResourceTypes" not in d:
                d["managedResourceTypes"] = []
            if "imagePatterns" not in d:
                d["imagePatterns"] = []
            for rt in d.get("resourceTemplates", []):
                for t in rt.get("targets", []):
                    ns = t["namespace"]
                    if "name" not in ns:
                        ns["name"] = "some_name"
                    if "environment" not in ns:
                        ns["environment"] = {}
                    if "app" not in ns:
                        ns["app"] = {}
                    if "cluster" not in ns:
                        ns["cluster"] = {}
        return [gql_class_factory(SaasFile, d) for d in data]

    return builder


@pytest.fixture
def vcs_builder() -> Callable[..., VCS]:
    def builder() -> VCS:
        vcs = create_autospec(spec=VCS)
        vcs.get_commit_sha.side_effect = ["new_sha"] * 100
        vcs._app_interface_api = MagicMock()
        return vcs

    return builder


@pytest.fixture
def gql_client_builder() -> Callable[..., GitLabApi]:
    def builder() -> GitLabApi:
        api = create_autospec(spec=GitLabApi)
        api.project = MagicMock()
        api.project.mergerequests = MagicMock()
        api.project.mergerequests.create.side_effect = []
        return api

    return builder


@pytest.fixture
def saas_target_namespace_builder(
    gql_class_factory: Callable[..., SaasTargetNamespace],
) -> Callable[..., SaasTargetNamespace]:
    def builder(data: MutableMapping) -> SaasTargetNamespace:
        if "environment" not in data:
            data["environment"] = {}
        if "app" not in data:
            data["app"] = {}
        if "cluster" not in data:
            data["cluster"] = {}
        return gql_class_factory(SaasTargetNamespace, data)

    return builder


@pytest.fixture
def promotion_state_builder() -> Callable[..., PromotionState]:
    def builder(data: Iterable[PromotionData]) -> PromotionState:
        promotion_state = create_autospec(spec=PromotionState)
        promotion_state.get_promotion_data.side_effect = data
        return promotion_state

    return builder


@pytest.fixture
def subscriber_builder(
    saas_target_namespace_builder: Callable[..., SaasTargetNamespace],
) -> Callable[[Mapping[str, Any]], Subscriber]:
    def builder(data: Mapping[str, Any]) -> Subscriber:
        channels: list[Channel] = []
        for channel_name, channel_data in data.get("CHANNELS", {}).items():
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
                    app_name="",
                    resource_template_name="",
                    target_name=None,
                    publish_job_logs=True,
                    has_subscriber=True,
                    auth_code=None,
                )
                publisher.commit_sha = publisher_data["REAL_WORLD_SHA"]
                publisher.deployment_info_by_channel[channel_name] = DeploymentInfo(
                    success=publisher_data.get("SUCCESSFUL_DEPLOYMENT", True),
                    target_config_hash=publisher_data.get("CONFIG_HASH", ""),
                    saas_file=publisher_name,
                    check_in=publisher_data.get("CHECK_IN", datetime.now(UTC)),
                )
                channel.publishers.append(publisher)
            channels.append(channel)
        cur_config_hashes_by_channel: dict[str, list[ConfigHash]] = defaultdict(list)
        for cur_config_hash in data.get("CUR_CONFIG_HASHES", []):
            cur_config_hashes_by_channel[cur_config_hash.channel].append(
                cur_config_hash
            )
        subscriber = Subscriber(
            uid=data.get("SUB_UID", "default"),
            target_namespace=saas_target_namespace_builder(data.get("NAMESPACE", {})),
            ref=data.get("CUR_SUBSCRIBER_REF", ""),
            saas_name="",
            target_file_path=data.get("TARGET_FILE_PATH", ""),
            template_name="",
            use_target_config_hash=data.get("USE_TARGET_CONFIG_HASH", True),
            soak_days=data.get("SOAK_DAYS", 0),
            blocked_versions=data.get("BLOCKED_VERSIONS", {}),
        )
        subscriber.channels = channels
        subscriber.config_hashes_by_channel_name = cur_config_hashes_by_channel
        subscriber.desired_ref = data.get("DESIRED_REF", "")
        subscriber.desired_hashes = data.get("DESIRED_TARGET_HASHES", [])
        return subscriber

    return builder
