from __future__ import annotations

from unittest.mock import (
    MagicMock,
    patch,
)

import pytest
from sretoolbox.container.image import (
    ImageComparisonError,
    ImageContainsError,
)
from sretoolbox.container.skopeo import SkopeoCmdError

from reconcile.container_registry_mirror.deep_sync_timer import DeepSyncTimer
from reconcile.container_registry_mirror.engine import MirrorEngine
from reconcile.container_registry_mirror.mirror_spec import MirrorSpec


def _make_spec(
    source_url: str = "docker.io/upstream/image",
    source_creds: str | None = "src_user:src_pass",
    destination_url: str = "quay.io/org/image",
    destination_creds: str = "dst_user:dst_pass",
    tag_include: list[str] | None = None,
    tag_exclude: list[str] | None = None,
) -> MirrorSpec:
    """Build a MirrorSpec with sensible defaults to reduce boilerplate
    in individual tests."""
    return MirrorSpec(
        source_url=source_url,
        source_creds=source_creds,
        destination_url=destination_url,
        destination_creds=destination_creds,
        tag_include=tag_include,
        tag_exclude=tag_exclude,
    )


def _make_source_image(tags: list[str]) -> MagicMock:
    """Create a mock Image for the source registry that yields the
    given tags when iterated."""
    img = MagicMock()
    img.__iter__ = MagicMock(return_value=iter(tags))
    # __getitem__ returns a new mock representing the image at a
    # specific tag. Each tag gets a distinct mock so assertions
    # can distinguish them.
    tag_images: dict[str, MagicMock] = {}
    for tag in tags:
        tag_img = MagicMock()
        tag_img.__str__ = MagicMock(return_value=f"docker.io/upstream/image:{tag}")  # type: ignore[method-assign]
        tag_images[tag] = tag_img

    def getitem(tag: str) -> MagicMock:
        if tag not in tag_images:
            tag_images[tag] = MagicMock()
            tag_images[tag].__str__ = MagicMock(  # type: ignore[method-assign]
                return_value=f"docker.io/upstream/image:{tag}"
            )
        return tag_images[tag]

    img.__getitem__ = MagicMock(side_effect=getitem)
    img.response_cache_hits = 0
    img.response_cache_misses = 0
    return img


def _make_dest_image(existing_tags: set[str]) -> MagicMock:
    """Create a mock Image for the destination registry. Tags in
    existing_tags return True for __contains__."""
    img = MagicMock()
    img.__contains__ = MagicMock(side_effect=lambda tag: tag in existing_tags)

    tag_images: dict[str, MagicMock] = {}

    def getitem(tag: str) -> MagicMock:
        if tag not in tag_images:
            tag_images[tag] = MagicMock()
            tag_images[tag].__str__ = MagicMock(return_value=f"quay.io/org/image:{tag}")  # type: ignore[method-assign]
        return tag_images[tag]

    img.__getitem__ = MagicMock(side_effect=getitem)
    img.response_cache_hits = 0
    img.response_cache_misses = 0
    return img


@pytest.fixture()
def skopeo() -> MagicMock:
    return MagicMock()


@pytest.fixture()
def engine(skopeo: MagicMock) -> MirrorEngine:
    return MirrorEngine(
        skopeo=skopeo,
        dry_run=False,
        is_deep_sync=False,
    )


@pytest.fixture()
def deep_sync_engine(skopeo: MagicMock) -> MirrorEngine:
    """An engine configured with deep sync enabled, for manifest
    comparison tests."""
    return MirrorEngine(
        skopeo=skopeo,
        dry_run=False,
        is_deep_sync=True,
    )


class TestMissingTagCopied:
    """When a tag exists at the source but not the destination,
    skopeo.copy must be called regardless of deep sync mode."""

    def test_missing_tag_triggers_copy(
        self, engine: MirrorEngine, skopeo: MagicMock
    ) -> None:
        spec = _make_spec()
        source = _make_source_image(["v1.0"])
        dest = _make_dest_image(set())

        with patch.object(engine, "_build_images", return_value=(source, dest)):
            engine.sync([spec])

        skopeo.copy.assert_called_once()
        copy_call = skopeo.copy.call_args
        assert "v1.0" in copy_call.kwargs.get(
            "src_image", copy_call.args[0] if copy_call.args else ""
        )

    def test_missing_tag_copied_with_correct_credentials(
        self, engine: MirrorEngine, skopeo: MagicMock
    ) -> None:
        spec = _make_spec(
            source_creds="pull_user:pull_pass",
            destination_creds="push_user:push_pass",
        )
        source = _make_source_image(["latest"])
        dest = _make_dest_image(set())

        with patch.object(engine, "_build_images", return_value=(source, dest)):
            engine.sync([spec])

        skopeo.copy.assert_called_once_with(
            src_image="docker.io/upstream/image:latest",
            src_creds="pull_user:pull_pass",
            dst_image="quay.io/org/image:latest",
            dest_creds="push_user:push_pass",
        )


class TestExistingTagFastMode:
    """When a tag exists at both registries and deep sync is off,
    no copy or manifest comparison should occur."""

    def test_existing_tag_skipped_in_fast_mode(
        self, engine: MirrorEngine, skopeo: MagicMock
    ) -> None:
        spec = _make_spec()
        source = _make_source_image(["v1.0"])
        dest = _make_dest_image({"v1.0"})

        with patch.object(engine, "_build_images", return_value=(source, dest)):
            engine.sync([spec])

        skopeo.copy.assert_not_called()

    def test_no_manifest_comparison_in_fast_mode(
        self, engine: MirrorEngine, skopeo: MagicMock
    ) -> None:
        """When deep sync is off, the destination tag's is_part_of
        should not be called, confirming no manifest comparison."""
        spec = _make_spec()
        source = _make_source_image(["v1.0"])
        dest = _make_dest_image({"v1.0"})
        dest_tag_mock = MagicMock()
        dest.__getitem__ = MagicMock(return_value=dest_tag_mock)

        with patch.object(engine, "_build_images", return_value=(source, dest)):
            engine.sync([spec])

        # is_part_of is only called during deep sync manifest comparison.
        dest_tag_mock.is_part_of.assert_not_called()


class TestDeepSyncInSync:
    """When deep sync is on and manifests match, no copy should occur."""

    def test_matching_manifests_skip_copy(
        self, deep_sync_engine: MirrorEngine, skopeo: MagicMock
    ) -> None:
        spec = _make_spec()
        source = _make_source_image(["v1.0"])
        dest = _make_dest_image({"v1.0"})

        # Make the downstream == upstream comparison return True.
        # Accessing source["v1.0"] ensures the mock creates the tag image.
        source["v1.0"]
        dest_tag = dest["v1.0"]
        dest_tag.__eq__ = MagicMock(return_value=True)

        with patch.object(
            deep_sync_engine, "_build_images", return_value=(source, dest)
        ):
            deep_sync_engine.sync([spec])

        skopeo.copy.assert_not_called()


class TestDeepSyncOutOfSync:
    """When deep sync is on and manifests differ, a copy must be queued."""

    def test_differing_manifests_trigger_copy(
        self, deep_sync_engine: MirrorEngine, skopeo: MagicMock
    ) -> None:
        spec = _make_spec()
        source = _make_source_image(["v1.0"])
        dest = _make_dest_image({"v1.0"})

        dest_tag = dest["v1.0"]
        dest_tag.__eq__ = MagicMock(return_value=False)
        dest_tag.is_part_of = MagicMock(return_value=False)

        with patch.object(
            deep_sync_engine, "_build_images", return_value=(source, dest)
        ):
            deep_sync_engine.sync([spec])

        skopeo.copy.assert_called_once()


class TestMultiArchMatch:
    """When the downstream single-arch image is part of the upstream
    multi-arch manifest list, no copy should occur."""

    def test_is_part_of_skips_copy(
        self, deep_sync_engine: MirrorEngine, skopeo: MagicMock
    ) -> None:
        spec = _make_spec()
        source = _make_source_image(["v1.0"])
        dest = _make_dest_image({"v1.0"})

        dest_tag = dest["v1.0"]
        # __eq__ returns False (manifests differ at the top level),
        # but is_part_of returns True (downstream is a component).
        dest_tag.__eq__ = MagicMock(return_value=False)
        dest_tag.is_part_of = MagicMock(return_value=True)

        with patch.object(
            deep_sync_engine, "_build_images", return_value=(source, dest)
        ):
            deep_sync_engine.sync([spec])

        skopeo.copy.assert_not_called()


class TestTagFiltering:
    """Tags must be filtered by include/exclude patterns before
    processing. Exclusions take precedence."""

    def test_excluded_tag_not_copied(
        self, engine: MirrorEngine, skopeo: MagicMock
    ) -> None:
        spec = _make_spec(tag_exclude=["^sha256-.+sig$"])
        source = _make_source_image(["sha256-abc123.sig", "v1.0"])
        dest = _make_dest_image(set())

        with patch.object(engine, "_build_images", return_value=(source, dest)):
            engine.sync([spec])

        # Only v1.0 should be copied; the sig tag is excluded.
        assert skopeo.copy.call_count == 1
        copy_call = skopeo.copy.call_args
        assert "v1.0" in str(copy_call)

    def test_non_matching_include_not_copied(
        self, engine: MirrorEngine, skopeo: MagicMock
    ) -> None:
        spec = _make_spec(tag_include=["^v[0-9]+"])
        source = _make_source_image(["latest", "v1.0", "v2.0"])
        dest = _make_dest_image(set())

        with patch.object(engine, "_build_images", return_value=(source, dest)):
            engine.sync([spec])

        # Only v1.0 and v2.0 match; latest does not.
        assert skopeo.copy.call_count == 2

    def test_exclude_takes_precedence_over_include(
        self, engine: MirrorEngine, skopeo: MagicMock
    ) -> None:
        spec = _make_spec(
            tag_include=["^v"],
            tag_exclude=["^v1\\.0$"],
        )
        source = _make_source_image(["v1.0", "v2.0"])
        dest = _make_dest_image(set())

        with patch.object(engine, "_build_images", return_value=(source, dest)):
            engine.sync([spec])

        # v1.0 matches include but also matches exclude; only v2.0 copied.
        assert skopeo.copy.call_count == 1


class TestMultipleSpecs:
    """The engine must process all specs, not just the first."""

    def test_all_specs_processed(self, engine: MirrorEngine, skopeo: MagicMock) -> None:
        spec_a = _make_spec(
            source_url="docker.io/upstream/image-a",
            destination_url="quay.io/org/image-a",
        )
        spec_b = _make_spec(
            source_url="docker.io/upstream/image-b",
            destination_url="quay.io/org/image-b",
        )

        source_a = _make_source_image(["v1"])
        dest_a = _make_dest_image(set())
        source_b = _make_source_image(["v2"])
        dest_b = _make_dest_image(set())

        images = iter([(source_a, dest_a), (source_b, dest_b)])

        with patch.object(
            engine, "_build_images", side_effect=lambda spec: next(images)
        ):
            engine.sync([spec_a, spec_b])

        assert skopeo.copy.call_count == 2


class TestEmptySpecList:
    """An empty spec list should produce no copies, no errors,
    and no timestamp recording."""

    def test_empty_specs_no_work(self, engine: MirrorEngine, skopeo: MagicMock) -> None:
        engine.sync([])
        skopeo.copy.assert_not_called()


class TestSourceHasNoTags:
    """When the source image has no tags, the loop completes with
    no work."""

    def test_no_tags_no_copies(self, engine: MirrorEngine, skopeo: MagicMock) -> None:
        spec = _make_spec()
        source = _make_source_image([])
        dest = _make_dest_image(set())

        with patch.object(engine, "_build_images", return_value=(source, dest)):
            engine.sync([spec])

        skopeo.copy.assert_not_called()


class TestAllTagsFilteredOut:
    """When all source tags are filtered out, no copies occur."""

    def test_all_filtered_no_copies(
        self, engine: MirrorEngine, skopeo: MagicMock
    ) -> None:
        spec = _make_spec(tag_exclude=[".*"])
        source = _make_source_image(["v1.0", "v2.0", "latest"])
        dest = _make_dest_image(set())

        with patch.object(engine, "_build_images", return_value=(source, dest)):
            engine.sync([spec])

        skopeo.copy.assert_not_called()


class TestImageComparisonError:
    """When a manifest cannot be fetched during comparison,
    that tag is skipped and processing continues."""

    def test_comparison_error_skips_tag(
        self, deep_sync_engine: MirrorEngine, skopeo: MagicMock
    ) -> None:
        spec = _make_spec()
        source = _make_source_image(["v1.0", "v2.0"])
        dest = _make_dest_image({"v1.0", "v2.0"})

        dest_v1 = dest["v1.0"]
        dest_v1.__eq__ = MagicMock(side_effect=ImageComparisonError("network error"))

        dest_v2 = dest["v2.0"]
        dest_v2.__eq__ = MagicMock(return_value=False)
        dest_v2.is_part_of = MagicMock(return_value=False)

        with patch.object(
            deep_sync_engine, "_build_images", return_value=(source, dest)
        ):
            deep_sync_engine.sync([spec])

        # v1.0 is skipped due to comparison error; v2.0 is out of sync
        # and should be copied.
        assert skopeo.copy.call_count == 1


class TestImageContainsError:
    """When is_part_of raises ImageContainsError (incompatible manifest
    types), the images are structurally different and should be copied."""

    def test_contains_error_triggers_copy(
        self, deep_sync_engine: MirrorEngine, skopeo: MagicMock
    ) -> None:
        spec = _make_spec()
        source = _make_source_image(["v1.0"])
        dest = _make_dest_image({"v1.0"})

        dest_tag = dest["v1.0"]
        dest_tag.__eq__ = MagicMock(return_value=False)
        dest_tag.is_part_of = MagicMock(
            side_effect=ImageContainsError("both single-arch")
        )

        with patch.object(
            deep_sync_engine, "_build_images", return_value=(source, dest)
        ):
            deep_sync_engine.sync([spec])

        skopeo.copy.assert_called_once()


class TestSkopeoCopyErrors:
    """Copy failures are collected and raised as an ExceptionGroup
    after all specs are processed."""

    def test_single_copy_failure_raises_exception_group(
        self, engine: MirrorEngine, skopeo: MagicMock
    ) -> None:
        spec = _make_spec()
        source = _make_source_image(["v1.0"])
        dest = _make_dest_image(set())
        skopeo.copy.side_effect = SkopeoCmdError("copy failed")

        with (
            patch.object(engine, "_build_images", return_value=(source, dest)),
            pytest.raises(ExceptionGroup) as exc_info,
        ):
            engine.sync([spec])

        assert len(exc_info.value.exceptions) == 1

    def test_multiple_copy_failures_all_collected(
        self, engine: MirrorEngine, skopeo: MagicMock
    ) -> None:
        spec = _make_spec()
        source = _make_source_image(["v1.0", "v2.0"])
        dest = _make_dest_image(set())
        skopeo.copy.side_effect = SkopeoCmdError("copy failed")

        with (
            patch.object(engine, "_build_images", return_value=(source, dest)),
            pytest.raises(ExceptionGroup) as exc_info,
        ):
            engine.sync([spec])

        assert len(exc_info.value.exceptions) == 2

    def test_mixed_success_and_failure(
        self, engine: MirrorEngine, skopeo: MagicMock
    ) -> None:
        """Successful copies complete; failures are collected; the
        ExceptionGroup contains only the failures."""
        spec = _make_spec()
        source = _make_source_image(["v1.0", "v2.0"])
        dest = _make_dest_image(set())
        # First copy succeeds, second fails.
        skopeo.copy.side_effect = [None, SkopeoCmdError("v2 failed")]

        with (
            patch.object(engine, "_build_images", return_value=(source, dest)),
            pytest.raises(ExceptionGroup) as exc_info,
        ):
            engine.sync([spec])

        assert len(exc_info.value.exceptions) == 1
        assert skopeo.copy.call_count == 2


class TestSourceCredsNone:
    """When source credentials are None (public source), skopeo.copy
    should be called with src_creds=None."""

    def test_none_source_creds_passed_through(
        self, engine: MirrorEngine, skopeo: MagicMock
    ) -> None:
        spec = _make_spec(source_creds=None)
        source = _make_source_image(["v1.0"])
        dest = _make_dest_image(set())

        with patch.object(engine, "_build_images", return_value=(source, dest)):
            engine.sync([spec])

        skopeo.copy.assert_called_once_with(
            src_image="docker.io/upstream/image:v1.0",
            src_creds=None,
            dst_image="quay.io/org/image:v1.0",
            dest_creds="dst_user:dst_pass",
        )


class TestBuildImages:
    """_build_images constructs Image objects from a MirrorSpec,
    splitting credentials into username and password."""

    def test_builds_images_with_credentials(self) -> None:
        engine = MirrorEngine(skopeo=MagicMock(), dry_run=False, is_deep_sync=False)
        spec = _make_spec(
            source_url="docker.io/upstream/image",
            source_creds="src_user:src_pass",
            destination_url="quay.io/org/image",
            destination_creds="dst_user:dst_pass",
        )

        source, dest = engine._build_images(spec)

        # Image.__str__ prepends "docker://" and appends ":latest".
        assert "docker.io/upstream/image" in str(source)
        assert "quay.io/org/image" in str(dest)
        assert source.username == "src_user"
        assert source.password == "src_pass"
        assert dest.username == "dst_user"
        assert dest.password == "dst_pass"

    def test_builds_images_with_none_source_creds(self) -> None:
        """When source credentials are None (public source), the source
        Image should be constructed without authentication."""
        engine = MirrorEngine(skopeo=MagicMock(), dry_run=False, is_deep_sync=False)
        spec = _make_spec(source_creds=None)

        source, _dest = engine._build_images(spec)

        assert source.username is None
        assert source.password is None


class TestImageClassParameter:
    """The engine accepts an image_class parameter so callers can pass
    InstrumentedImage (or any Image subclass) instead of the default."""

    def test_uses_provided_image_class(self) -> None:
        """When image_class is provided, _build_images should construct
        instances of that class instead of sretoolbox's Image."""

        class FakeImage:
            def __init__(self, url: str, **kwargs: object) -> None:
                self.url = url
                self.kwargs = kwargs

        engine = MirrorEngine(
            skopeo=MagicMock(),
            dry_run=False,
            is_deep_sync=False,
            image_class=FakeImage,
        )
        spec = _make_spec(
            source_creds="user:pass",
            destination_creds="dst:pass",
        )

        source, dest = engine._build_images(spec)

        assert isinstance(source, FakeImage)
        assert isinstance(dest, FakeImage)

    def test_default_image_class_uses_sretoolbox(self) -> None:
        """When image_class is None (default), _build_images should
        use sretoolbox's Image."""
        engine = MirrorEngine(skopeo=MagicMock(), dry_run=False, is_deep_sync=False)
        spec = _make_spec(
            source_creds="user:pass",
            destination_creds="dst:pass",
        )

        source, dest = engine._build_images(spec)

        from sretoolbox.container import Image

        assert isinstance(source, Image)
        assert isinstance(dest, Image)


class TestResponseCacheParameter:
    """The engine accepts a shared response_cache dict so that manifest
    fetches are deduplicated across repos within a single sync run."""

    def test_cache_passed_to_image_constructor(self) -> None:
        """When response_cache is provided, it should be forwarded to
        each Image constructor as a keyword argument."""
        cache: dict = {}
        calls: list[dict] = []

        class SpyImage:
            def __init__(self, url: str, **kwargs: object) -> None:
                calls.append(kwargs)

        engine = MirrorEngine(
            skopeo=MagicMock(),
            image_class=SpyImage,
            response_cache=cache,
        )
        spec = _make_spec(
            source_creds="user:pass",
            destination_creds="dst:pass",
        )

        engine._build_images(spec)

        # Both source and destination Image should receive the cache.
        assert len(calls) == 2
        assert calls[0]["response_cache"] is cache
        assert calls[1]["response_cache"] is cache

    def test_no_cache_when_not_provided(self) -> None:
        """When response_cache is None, the keyword should not be
        passed to Image constructors."""
        calls: list[dict] = []

        class SpyImage:
            def __init__(self, url: str, **kwargs: object) -> None:
                calls.append(kwargs)

        engine = MirrorEngine(
            skopeo=MagicMock(),
            image_class=SpyImage,
        )
        spec = _make_spec(
            source_creds="user:pass",
            destination_creds="dst:pass",
        )

        engine._build_images(spec)

        assert "response_cache" not in calls[0]
        assert "response_cache" not in calls[1]


class TestSessionParameter:
    """The engine accepts a shared requests.Session for TCP connection
    pooling across Image instances."""

    def test_session_passed_to_image_constructor(self) -> None:
        """When session is provided, it should be forwarded to each
        Image constructor."""
        session = MagicMock()
        calls: list[dict] = []

        class SpyImage:
            def __init__(self, url: str, **kwargs: object) -> None:
                calls.append(kwargs)

        engine = MirrorEngine(
            skopeo=MagicMock(),
            image_class=SpyImage,
            session=session,
        )
        spec = _make_spec(
            source_creds="user:pass",
            destination_creds="dst:pass",
        )

        engine._build_images(spec)

        assert calls[0]["session"] is session
        assert calls[1]["session"] is session

    def test_no_session_when_not_provided(self) -> None:
        """When session is None, the keyword should not be passed."""
        calls: list[dict] = []

        class SpyImage:
            def __init__(self, url: str, **kwargs: object) -> None:
                calls.append(kwargs)

        engine = MirrorEngine(
            skopeo=MagicMock(),
            image_class=SpyImage,
        )
        spec = _make_spec(
            source_creds="user:pass",
            destination_creds="dst:pass",
        )

        engine._build_images(spec)

        assert "session" not in calls[0]
        assert "session" not in calls[1]

    def test_cache_and_session_combined(self) -> None:
        """When both response_cache and session are provided, both
        should be forwarded together."""
        cache: dict = {}
        session = MagicMock()
        calls: list[dict] = []

        class SpyImage:
            def __init__(self, url: str, **kwargs: object) -> None:
                calls.append(kwargs)

        engine = MirrorEngine(
            skopeo=MagicMock(),
            image_class=SpyImage,
            response_cache=cache,
            session=session,
        )
        spec = _make_spec(
            source_creds="user:pass",
            destination_creds="dst:pass",
        )

        engine._build_images(spec)

        assert calls[0]["response_cache"] is cache
        assert calls[0]["session"] is session
        assert calls[1]["response_cache"] is cache
        assert calls[1]["session"] is session


class TestDeepSyncCopyAfterContainsError:
    """Verify the copy in the deep sync path (not the missing-tag path)
    is exercised when ImageContainsError triggers a re-mirror."""

    def test_copy_uses_correct_credentials_after_contains_error(
        self, deep_sync_engine: MirrorEngine, skopeo: MagicMock
    ) -> None:
        spec = _make_spec(
            source_creds="pull:pass",
            destination_creds="push:pass",
        )
        source = _make_source_image(["v1.0"])
        # Tag exists at destination, so the deep sync path runs.
        dest = _make_dest_image({"v1.0"})

        dest_tag = dest["v1.0"]
        dest_tag.__eq__ = MagicMock(return_value=False)
        dest_tag.is_part_of = MagicMock(side_effect=ImageContainsError("incompatible"))

        with patch.object(
            deep_sync_engine, "_build_images", return_value=(source, dest)
        ):
            deep_sync_engine.sync([spec])

        skopeo.copy.assert_called_once_with(
            src_image="docker.io/upstream/image:v1.0",
            src_creds="pull:pass",
            dst_image="quay.io/org/image:v1.0",
            dest_creds="push:pass",
        )


class TestDeepSyncTimerIntegration:
    """The engine should consult a DeepSyncTimer to decide whether
    deep sync runs, and record the timestamp after success."""

    def test_timer_determines_deep_sync(self) -> None:
        """When a DeepSyncTimer is provided with should_run=True,
        the engine's is_deep_sync should be True."""
        timer = MagicMock(spec=DeepSyncTimer)
        timer.should_run = True

        engine = MirrorEngine(
            skopeo=MagicMock(),
            dry_run=False,
            deep_sync_timer=timer,
        )

        assert engine.is_deep_sync is True

    def test_timer_disables_deep_sync(self) -> None:
        """When a DeepSyncTimer is provided with should_run=False,
        the engine's is_deep_sync should be False."""
        timer = MagicMock(spec=DeepSyncTimer)
        timer.should_run = False

        engine = MirrorEngine(
            skopeo=MagicMock(),
            dry_run=False,
            deep_sync_timer=timer,
        )

        assert engine.is_deep_sync is False

    def test_timer_overrides_is_deep_sync_bool(self) -> None:
        """When both deep_sync_timer and is_deep_sync are provided,
        the timer takes precedence."""
        timer = MagicMock(spec=DeepSyncTimer)
        timer.should_run = False

        engine = MirrorEngine(
            skopeo=MagicMock(),
            dry_run=False,
            is_deep_sync=True,
            deep_sync_timer=timer,
        )

        assert engine.is_deep_sync is False


class TestTimerRecordOnSuccess:
    """The engine should record the timestamp only after a successful
    deep sync (no errors, not dry-run)."""

    def test_records_timestamp_after_successful_deep_sync(self) -> None:
        timer = MagicMock(spec=DeepSyncTimer)
        timer.should_run = True
        skopeo = MagicMock()
        engine = MirrorEngine(
            skopeo=skopeo,
            dry_run=False,
            deep_sync_timer=timer,
        )
        spec = _make_spec()
        source = _make_source_image(["v1.0"])
        dest = _make_dest_image(set())

        with patch.object(engine, "_build_images", return_value=(source, dest)):
            engine.sync([spec])

        timer.record.assert_called_once()

    def test_does_not_record_in_dry_run(self) -> None:
        timer = MagicMock(spec=DeepSyncTimer)
        timer.should_run = True
        engine = MirrorEngine(
            skopeo=MagicMock(),
            dry_run=True,
            deep_sync_timer=timer,
        )

        engine.sync([])

        timer.record.assert_not_called()

    def test_does_not_record_when_not_deep_sync(self) -> None:
        timer = MagicMock(spec=DeepSyncTimer)
        timer.should_run = False
        engine = MirrorEngine(
            skopeo=MagicMock(),
            dry_run=False,
            deep_sync_timer=timer,
        )

        engine.sync([])

        timer.record.assert_not_called()

    def test_does_not_record_on_copy_failure(self) -> None:
        """When copies fail, the ExceptionGroup should be raised
        before the timestamp is recorded."""
        timer = MagicMock(spec=DeepSyncTimer)
        timer.should_run = True
        skopeo = MagicMock()
        skopeo.copy.side_effect = SkopeoCmdError("failed")
        engine = MirrorEngine(
            skopeo=skopeo,
            dry_run=False,
            deep_sync_timer=timer,
        )
        spec = _make_spec()
        source = _make_source_image(["v1.0"])
        dest = _make_dest_image(set())

        with (
            patch.object(engine, "_build_images", return_value=(source, dest)),
            pytest.raises(ExceptionGroup),
        ):
            engine.sync([spec])

        timer.record.assert_not_called()
