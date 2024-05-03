from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from reconcile.typed_queries.saas_files import SaasFile
from reconcile.utils.secret_reader import HasSecret


@dataclass
class SaasTarget:
    app_name: str
    repo_url: str
    namespace_name: str
    target_name: str
    ref: str
    auth_code: HasSecret | None


@dataclass
class Channel:
    name: str
    subscribers: list[SaasTarget]
    publishers: list[SaasTarget]


def build_channels(saas_files: Iterable[SaasFile]) -> list[Channel]:
    channels: dict[str, Channel] = {}
    for saas_file in saas_files:
        for resource_template in saas_file.resource_templates:
            for target in resource_template.targets:
                if not target.promotion:
                    continue
                if not (target.promotion.publish or target.promotion.subscribe):
                    continue
                auth_code = (
                    saas_file.authentication.code if saas_file.authentication else None
                )
                target_name = target.name if target.name else "NoName"
                saas_target = SaasTarget(
                    app_name=saas_file.app.name,
                    repo_url=resource_template.url,
                    ref=target.ref,
                    auth_code=auth_code,
                    namespace_name=target.namespace.name,
                    target_name=target_name,
                )

                for channel in target.promotion.publish or []:
                    if channel not in channels:
                        channels[channel] = Channel(
                            name=channel, subscribers=[], publishers=[]
                        )
                    channels[channel].publishers.append(saas_target)

                for channel in target.promotion.subscribe or []:
                    if channel not in channels:
                        channels[channel] = Channel(
                            name=channel, subscribers=[], publishers=[]
                        )
                    channels[channel].subscribers.append(saas_target)

    return list(channels.values())
