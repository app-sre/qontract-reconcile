from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from sretoolbox.container.image import (
    ImageComparisonError,
    ImageContainsError,
)
from sretoolbox.container.skopeo import SkopeoCmdError

from reconcile.utils.quay_mirror import sync_tag

if TYPE_CHECKING:
    from reconcile.container_registry_mirror.deep_sync_timer import DeepSyncTimer
    from reconcile.container_registry_mirror.mirror_spec import MirrorSpec

_LOG = logging.getLogger(__name__)


class MirrorEngine:
    """Runs the tag sync algorithm against a list of MirrorSpecs.
    Does not know or care which implementation produced the specs.
    The caller decides whether to pass instrumented or plain Image/Skopeo."""

    def __init__(
        self,
        skopeo: Any,
        dry_run: bool = False,
        is_deep_sync: bool = False,
        deep_sync_timer: DeepSyncTimer | None = None,
    ) -> None:
        self.skopeo = skopeo
        self.dry_run = dry_run
        # When a timer is provided, it determines whether deep sync
        # runs and handles timestamp recording. The is_deep_sync bool
        # is kept for backward compatibility with callers that do not
        # use a timer.
        self._deep_sync_timer = deep_sync_timer
        if deep_sync_timer is not None:
            self.is_deep_sync = deep_sync_timer.should_run
        else:
            self.is_deep_sync = is_deep_sync

    def _build_images(self, spec: MirrorSpec) -> tuple[Any, Any]:
        """Build source and destination Image objects for a spec.
        Exists as a separate method so tests can patch it without
        needing to mock the Image constructor import path."""
        from sretoolbox.container import Image  # noqa: PLC0415

        # maxsplit=1 preserves colons in passwords (e.g., base64-decoded
        # GCP service account keys frequently contain colons).
        if spec.source_creds:
            src_user, src_pass = spec.source_creds.split(":", maxsplit=1)
        else:
            src_user, src_pass = None, None

        dst_user, dst_pass = spec.destination_creds.split(":", maxsplit=1)

        source = Image(
            spec.source_url,
            username=src_user,
            password=src_pass,
        )
        dest = Image(
            spec.destination_url,
            username=dst_user,
            password=dst_pass,
        )
        return source, dest

    def sync(self, specs: list[MirrorSpec]) -> None:
        """Process all mirror specs: enumerate tags, filter, compare,
        and copy. Individual copy failures are collected and raised as
        an ExceptionGroup at the end so that one broken mirror does not
        prevent the rest from syncing."""
        errors: list[Exception] = []

        for spec in specs:
            source_image, dest_image = self._build_images(spec)

            for tag in source_image:
                if not sync_tag(
                    tags=spec.tag_include,
                    tags_exclude=spec.tag_exclude,
                    candidate=tag,
                ):
                    continue

                upstream = source_image[tag]
                downstream = dest_image[tag]

                # Fast path: tag does not exist at destination, so it
                # must be copied regardless of deep sync mode.
                if tag not in dest_image:
                    _LOG.debug(
                        "Image %s does not exist. Syncing from %s",
                        downstream,
                        upstream,
                    )
                    try:
                        self.skopeo.copy(
                            src_image=str(upstream),
                            src_creds=spec.source_creds,
                            dst_image=str(downstream),
                            dest_creds=spec.destination_creds,
                        )
                    except SkopeoCmdError as details:
                        _LOG.error("skopeo command error: '%s'", details)
                        errors.append(details)
                    continue

                # Slow path: tag exists at destination. Only compare
                # manifests when deep sync is active, to detect drift
                # on mutable tags.
                if not self.is_deep_sync:
                    _LOG.debug(
                        "Fast mode: skipping comparison of %s and %s",
                        downstream,
                        upstream,
                    )
                    continue

                should_copy = False
                try:
                    if downstream == upstream:
                        _LOG.debug(
                            "Image %s and mirror %s are in sync",
                            downstream,
                            upstream,
                        )
                        continue
                    # Multi-arch case: destination may be a single-arch
                    # component of the upstream multi-arch manifest list.
                    if downstream.is_part_of(upstream):
                        _LOG.debug(
                            "Image %s is part of multi-arch image %s",
                            downstream,
                            upstream,
                        )
                        continue
                    should_copy = True
                except ImageComparisonError as details:
                    # Manifest could not be fetched (network/auth/404).
                    # Skip this tag rather than failing the entire run.
                    _LOG.error(
                        "Error comparing %s and %s: %s",
                        downstream,
                        upstream,
                        details,
                    )
                    continue
                except ImageContainsError:
                    # Manifest types are incompatible for is_part_of
                    # (e.g., both single-arch). The images are
                    # structurally different, so copy.
                    should_copy = True

                if should_copy:
                    _LOG.debug(
                        "Image %s and mirror %s are out of sync",
                        downstream,
                        upstream,
                    )
                    try:
                        self.skopeo.copy(
                            src_image=str(upstream),
                            src_creds=spec.source_creds,
                            dst_image=str(downstream),
                            dest_creds=spec.destination_creds,
                        )
                    except SkopeoCmdError as details:
                        _LOG.error("skopeo command error: '%s'", details)
                        errors.append(details)

        # Raise before recording the timestamp so that a failed deep
        # sync is not marked as successful. Otherwise, failed images
        # would not be re-compared until the full interval elapses.
        if errors:
            raise ExceptionGroup("skopeo copy failures", errors)

        # Record the deep sync timestamp only when a real deep sync
        # completed without errors and not in dry-run mode.
        if self._deep_sync_timer and self.is_deep_sync and not self.dry_run:
            self._deep_sync_timer.record()
