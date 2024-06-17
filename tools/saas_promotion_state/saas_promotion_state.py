from __future__ import annotations

from collections.abc import Iterable

from reconcile.openshift_saas_deploy import (
    QONTRACT_INTEGRATION as OPENSHIFT_SAAS_DEPLOY,
)
from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.typed_queries.saas_files import SaasFile, get_saas_files
from reconcile.utils.promotion_state import PromotionData, PromotionState
from reconcile.utils.secret_reader import create_secret_reader
from reconcile.utils.state import init_state


class SaasPromotionStateException(Exception):
    pass


class SaasPromotionStateMissingException(Exception):
    pass


class SaasPromotionState:
    def __init__(
        self, promotion_state: PromotionState, saas_files: Iterable[SaasFile]
    ) -> None:
        self._promotion_state = promotion_state
        self._saas_files = saas_files

    def _publisher_ids_for_channel(
        self, channel: str, saas_files: Iterable[SaasFile]
    ) -> list[str]:
        publisher_uids: list[str] = []
        for saas_file in saas_files:
            for resource_template in saas_file.resource_templates:
                for target in resource_template.targets:
                    if not target.promotion:
                        continue
                    for publish_channel in target.promotion.publish or []:
                        if publish_channel == channel:
                            publisher_uids.append(
                                target.uid(
                                    parent_saas_file_name=saas_file.name,
                                    parent_resource_template_name=resource_template.name,
                                )
                            )
        return publisher_uids

    def get(self, channel: str, sha: str) -> dict[str, PromotionData | None]:
        return {
            publisher_id: self._promotion_state.get_promotion_data(
                sha=sha,
                channel=channel,
                use_cache=False,
                target_uid=publisher_id,
                pre_check_sha_exists=False,
            )
            for publisher_id in self._publisher_ids_for_channel(
                channel=channel, saas_files=self._saas_files
            )
        }

    def set_successful(self, channel: str, sha: str, publisher_uid: str) -> None:
        current_data = self._promotion_state.get_promotion_data(
            sha=sha,
            channel=channel,
            target_uid=publisher_uid,
            use_cache=False,
            pre_check_sha_exists=False,
        )

        if not current_data:
            raise SaasPromotionStateMissingException(
                f"No promotion state in S3 for given {publisher_uid=} {sha=} {channel=}"
            )

        if current_data.success:
            raise SaasPromotionStateException(
                f"The current promotion state is already marked successful for given {publisher_uid=} {sha=} {channel=}",
                current_data,
            )

        current_data.success = True
        self._promotion_state.publish_promotion_data(
            data=current_data, sha=sha, channel=channel, target_uid=publisher_uid
        )

    @staticmethod
    def create(
        promotion_state: PromotionState | None, saas_files: Iterable[SaasFile] | None
    ) -> SaasPromotionState:
        if not promotion_state:
            vault_settings = get_app_interface_vault_settings()
            secret_reader = create_secret_reader(use_vault=vault_settings.vault)
            saas_deploy_state = init_state(
                integration=OPENSHIFT_SAAS_DEPLOY, secret_reader=secret_reader
            )
            promotion_state = PromotionState(state=saas_deploy_state)
        if not saas_files:
            saas_files = get_saas_files()
        return SaasPromotionState(
            promotion_state=promotion_state, saas_files=saas_files
        )
