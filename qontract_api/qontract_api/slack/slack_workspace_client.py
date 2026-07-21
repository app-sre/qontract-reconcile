"""SlackWorkspaceClient: Caching + compute layer for Slack workspace data.

This layer sits between the stateless SlackApi and business logic, providing:
- Two-tier caching (memory + Redis) for Slack data
- Distributed locking for thread-safe cache updates
- Cache updates instead of invalidation (O(1) performance)
- Compute helpers (e.g., get_users_by_ids, get_usergroup_by_handle)
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel, Field
from qontract_utils.slack_api import (
    ChatPostMessageResponse,
    SlackApi,
    SlackApiError,
    SlackMessage,
    UserNotFoundError,
)
from qontract_utils.slack_api import SlackChannel as SlackChannelAPI
from qontract_utils.slack_api import SlackUser as SlackUserAPI
from qontract_utils.slack_api import SlackUsergroup as SlackUsergroupAPI

from qontract_api.logger import get_logger

from .domain import (
    SlackUsergroup,
    SlackUsergroupConfig,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from qontract_api.cache.base import CacheBackend
    from qontract_api.config import Settings

logger = get_logger(__name__)

# Matches "@handle" tokens not preceded by a non-whitespace character, so it
# skips things like "user@example.com" while still catching "@handle" at the
# start of a message or after whitespace/punctuation.
_MENTION_PATTERN = re.compile(r"(?<!\S)@([\w-]+)")


@runtime_checkable
class TypeWithId(Protocol):
    @property
    def id(self) -> str: ...


T = TypeVar("T", bound=TypeWithId)


class CachedUsers(BaseModel, frozen=True):
    """Cached dict of SlackUserAPI objects (for two-tier cache serialization)."""

    items: list[SlackUserAPI] = Field(default_factory=list)

    def to_dict(self) -> dict[str, SlackUserAPI]:
        """Convert to dict keyed by ID."""
        return {user.id: user for user in self.items}

    @classmethod
    def from_dict(cls, obj_dict: dict[str, SlackUserAPI]) -> CachedUsers:
        """Create from dict keyed by ID."""
        return cls(items=list(obj_dict.values()))


class CachedUsergroups(BaseModel, frozen=True):
    """Cached dict of SlackUsergroupAPI objects (for two-tier cache serialization)."""

    items: list[SlackUsergroupAPI] = Field(default_factory=list)

    def to_dict(self) -> dict[str, SlackUsergroupAPI]:
        """Convert to dict keyed by ID."""
        return {ug.id: ug for ug in self.items}

    @classmethod
    def from_dict(cls, obj_dict: dict[str, SlackUsergroupAPI]) -> CachedUsergroups:
        """Create from dict keyed by ID."""
        return cls(items=list(obj_dict.values()))


class CachedChannels(BaseModel, frozen=True):
    """Cached dict of SlackChannelAPI objects (for two-tier cache serialization)."""

    items: list[SlackChannelAPI] = Field(default_factory=list)

    def to_dict(self) -> dict[str, SlackChannelAPI]:
        """Convert to dict keyed by ID."""
        return {ch.id: ch for ch in self.items}

    @classmethod
    def from_dict(cls, obj_dict: dict[str, SlackChannelAPI]) -> CachedChannels:
        """Create from dict keyed by ID."""
        return cls(items=list(obj_dict.values()))


class SlackUsergroupNotFoundError(Exception):
    """Raised when a Slack usergroup is not found."""


class SlackWorkspaceClient:
    """Caching + compute layer for Slack workspace data.

    Provides:
    - Cached access to users, usergroups, and channels with TTL
    - Distributed locking for thread-safe cache updates
    - Cache updates instead of invalidation for better performance
    - Compute helpers for common operations
    """

    def __init__(
        self,
        slack_api: SlackApi,
        cache: CacheBackend,
        settings: Settings,
    ) -> None:
        """Initialize SlackWorkspaceClient.

        Args:
            slack_api: Stateless Slack API client
            cache: Cache backend with two-tier caching (memory + Redis)
            settings: Application settings with Slack config
        """
        self.slack_api = slack_api
        self.cache = cache
        self.settings = settings

    # CACHE KEY HELPERS
    def _cache_key_users(self) -> str:
        """Generate cache key for users."""
        return f"slack:{self.slack_api.workspace_name}:users"

    def _cache_key_usergroups(self) -> str:
        """Generate cache key for usergroups."""
        return f"slack:{self.slack_api.workspace_name}:usergroups"

    def _cache_key_channels(self) -> str:
        """Generate cache key for channels."""
        return f"slack:{self.slack_api.workspace_name}:channels"

    # CACHE OPERATIONS (using two-tier cache from CacheBackend)
    def _get_cached_users(self, cache_key: str) -> dict[str, SlackUserAPI] | None:
        """Get cached users"""
        cached = self.cache.get_obj(cache_key, CachedUsers)
        return cached.to_dict() if cached else None

    def _set_cached_users(
        self, cache_key: str, users: dict[str, SlackUserAPI], ttl: int
    ) -> None:
        """Set cached users"""
        cached = CachedUsers.from_dict(users)
        self.cache.set_obj(cache_key, cached, ttl)

    def _get_cached_usergroups(
        self, cache_key: str
    ) -> dict[str, SlackUsergroupAPI] | None:
        """Get cached usergroups"""
        cached = self.cache.get_obj(cache_key, CachedUsergroups)
        return cached.to_dict() if cached else None

    def _set_cached_usergroups(
        self, cache_key: str, usergroups: dict[str, SlackUsergroupAPI], ttl: int
    ) -> None:
        """Set cached usergroups"""
        cached = CachedUsergroups.from_dict(usergroups)
        self.cache.set_obj(cache_key, cached, ttl)

    def _get_cached_channels(self, cache_key: str) -> dict[str, SlackChannelAPI] | None:
        """Get cached channels"""
        cached = self.cache.get_obj(cache_key, CachedChannels)
        return cached.to_dict() if cached else None

    def _set_cached_channels(
        self, cache_key: str, channels: dict[str, SlackChannelAPI], ttl: int
    ) -> None:
        """Set cached channels"""
        cached = CachedChannels.from_dict(channels)
        self.cache.set_obj(cache_key, cached, ttl)

    def _clear_cache(self, cache_key: str) -> None:
        """Clear cache for given key."""
        try:
            with self.cache.lock(cache_key):
                self.cache.delete(cache_key)
        except RuntimeError as e:
            logger.warning(f"Could not acquire lock for {cache_key}: {e}")

    # CACHED DATA ACCESS
    def get_users(self) -> dict[str, SlackUserAPI]:
        """Get all users by ID (cached with distributed locking).

        Returns:
            Dict of SlackUserAPI objects by user ID
        """
        cache_key = self._cache_key_users()

        # Try cache first (no lock for reads)
        if cached := self._get_cached_users(cache_key):
            return cached

        with self.cache.lock(cache_key):
            # Double-check after lock
            if cached := self._get_cached_users(cache_key):
                return cached

            # Fetch from API
            users = {user.id: user for user in self.slack_api.users_list()}

            # Cache
            self._set_cached_users(
                cache_key, users, self.settings.slack.users_cache_ttl
            )

            return users

    def get_usergroups(self) -> dict[str, SlackUsergroupAPI]:
        """Get all usergroups by ID (cached with distributed locking).

        Returns:
            Dict of SlackUsergroupAPI objects by usergroup ID
        """
        cache_key = self._cache_key_usergroups()

        # Try cache first (no lock for reads)
        if cached := self._get_cached_usergroups(cache_key):
            return cached

        with self.cache.lock(cache_key):
            # Double-check after lock
            if cached := self._get_cached_usergroups(cache_key):
                return cached

            # Fetch from API
            usergroups = {ug.id: ug for ug in self.slack_api.usergroups_list()}

            # Cache
            self._set_cached_usergroups(
                cache_key, usergroups, self.settings.slack.usergroup_cache_ttl
            )

            return usergroups

    def get_channels(self) -> dict[str, SlackChannelAPI]:
        """Get all channels by ID (cached with distributed locking).

        Returns:
            Dict of SlackChannelAPI objects by channel ID
        """
        cache_key = self._cache_key_channels()

        # Try cache first (no lock for reads)
        if cached := self._get_cached_channels(cache_key):
            return cached

        with self.cache.lock(cache_key):
            # Double-check after lock
            if cached := self._get_cached_channels(cache_key):
                return cached

            # Fetch from API
            channels = {ch.id: ch for ch in self.slack_api.conversations_list()}

            # Cache
            self._set_cached_channels(
                cache_key, channels, self.settings.slack.channels_cache_ttl
            )

            return channels

    # COMPUTE HELPERS
    def _get_usergroup_by_handle(self, handle: str) -> SlackUsergroupAPI | None:
        """Get usergroup by handle.

        Args:
            handle: Usergroup handle (e.g., "oncall-team")

        Returns:
            SlackUsergroupAPI object or None if not found
        """
        usergroups = self.get_usergroups()
        for ug in usergroups.values():
            if ug.handle == handle:
                return ug
        return None

    # PUBLIC HELPERS
    def get_slack_usergroups(self, handles: list[str]) -> list:
        """Get Slack usergroups by handles.

        Args:
            handles: List of usergroup handles (e.g., ["oncall-team", "dev-team"])

        Returns:
            List of SlackUsergroup objects
        """
        usergroups = [
            ug for ug in self.get_usergroups().values() if ug.handle in handles
        ]
        channel_name_by_id = {
            channel.id: channel.name for channel in self.get_channels().values()
        }
        # Build lookup covering both workspace IDs (U...) and enterprise IDs (W...).
        # usergroups_list returns workspace-level U... IDs in ug.users, but user.id
        # returns the enterprise W... ID for Enterprise Grid users. Without both keys,
        # Enterprise Grid users are silently dropped from current state every reconcile.
        org_username_by_id: dict[str, str] = {}
        for user in self.get_users().values():
            org_username_by_id[user.pk] = user.org_username
            if user.enterprise_user:
                org_username_by_id[user.enterprise_user.id] = user.org_username

        return [
            SlackUsergroup(
                handle=ug.handle,
                config=SlackUsergroupConfig(
                    description=ug.description,
                    users=[
                        org_username_by_id[pk]
                        for pk in ug.users
                        if pk in org_username_by_id
                    ],
                    channels=[
                        channel_name_by_id[pk]
                        for pk in ug.prefs.channels
                        if pk in channel_name_by_id
                    ],
                ),
            )
            for ug in usergroups
        ]

    def clean_slack_usergroups(
        self, usergroups: Iterable[SlackUsergroup]
    ) -> list[SlackUsergroup]:
        """Clean usergroups by removing non-existing users/channels (efficient batch operation).

        Args:
            usergroups: List of usergroups to clean

        Returns:
            List of cleaned usergroups with only valid users/channels
        """
        # Pre-fetch all data ONCE for all usergroups (2 cache lookups total!)
        # Build O(1) lookup sets ONCE
        valid_org_names = {
            user.org_username for user in self.get_users().values() if not user.deleted
        }
        valid_channel_names = {channel.name for channel in self.get_channels().values()}

        # Filter all usergroups in-memory (very fast!)
        return [
            SlackUsergroup(
                handle=ug.handle,
                config=SlackUsergroupConfig(
                    description=ug.config.description,
                    users=[name for name in ug.config.users if name in valid_org_names],
                    channels=[
                        name
                        for name in ug.config.channels
                        if name.lstrip("#") in valid_channel_names
                    ],
                    notifications=ug.config.notifications,
                ),
            )
            for ug in usergroups
        ]

    def create_usergroup(
        self,
        *,
        handle: str,
        name: str | None = None,
    ) -> SlackUsergroupAPI:
        """Create a new usergroup and add to cache.

        Args:
            handle: Usergroup handle (e.g., "oncall-team")
            name: Usergroup display name (defaults to handle)

        Returns:
            Created SlackUsergroupAPI object
        """
        created_ug = self.slack_api.usergroup_create(handle=handle, name=name)

        # Add to cache
        try:
            with self.cache.lock(self._cache_key_usergroups()):
                cached = self._get_cached_usergroups(self._cache_key_usergroups())
                if cached:
                    cached[created_ug.id] = created_ug
                    self._set_cached_usergroups(
                        self._cache_key_usergroups(),
                        cached,
                        self.settings.slack.usergroup_cache_ttl,
                    )
        except RuntimeError as e:
            logger.warning(f"Could not acquire lock to cache created usergroup: {e}")

        return created_ug

    def update_usergroup(
        self, *, handle: str, description: str, channels: Iterable[str]
    ) -> None:
        """Update usergroup and cache (O(1) update, not invalidation).

        Args:
            handle: Usergroup handle (e.g., "oncall-team")
            description: Short description of the usergroup
            channels: List of channel names associate with the usergroup
        """
        # Get usergroup by handle
        ug = self._get_usergroup_by_handle(handle)
        if not ug:
            raise SlackUsergroupNotFoundError(f"Usergroup {handle} not found!")

        channel_id_by_name = {
            channel.name: pk for pk, channel in self.get_channels().items()
        }
        # Always clear the usergroup cache (will be repopulated on next read)
        self._clear_cache(self._cache_key_usergroups())

        self.slack_api.usergroup_update(
            usergroup_id=ug.id,
            description=description,
            channel_ids=[channel_id_by_name[ch.lstrip("#")] for ch in channels],
        )

    def update_usergroup_users(
        self,
        *,
        handle: str,
        users: Iterable[str],
    ) -> None:
        """Update usergroup users.

        Args:
            handle: Usergroup handle (e.g., "oncall-team")
            users: List of org usernames (will be mapped to Slack user IDs)
        """
        # TODO: https://github.com/app-sre/qontract-reconcile/pull/5304#discussion_r2715066336
        # Get usergroup by handle
        ug = self._get_usergroup_by_handle(handle)
        if not ug:
            raise SlackUsergroupNotFoundError(f"Usergroup {handle} not found!")

        all_users = self.get_users()
        if users:
            # Map user names to IDs
            user_id_by_org_name = {
                user.org_username: user.id
                for user in all_users.values()
                if not user.deleted
            }
            user_ids = [user_id_by_org_name[name] for name in users]
        else:
            # Slack API does not allow empty user lists and we don't want to disable
            # the usergroup to keep the handle alive. The trick is passing a random deleted user.
            try:
                user_ids = [
                    next(user.id for user in all_users.values() if user.deleted)
                ]
            except StopIteration:
                raise RuntimeError(
                    "No deleted users found to assign to empty usergroup"
                ) from None

        if not ug.is_active():
            # Reactivate usergroup if it was disabled
            self.slack_api.usergroup_enable(usergroup_id=ug.id)

        # Always clear the usergroup cache (will be repopulated on next read)
        self._clear_cache(self._cache_key_usergroups())

        try:
            self.slack_api.usergroup_users_update(usergroup_id=ug.id, user_ids=user_ids)
        except SlackApiError as e:
            # Slack can throw an invalid_users error when emptying groups, but
            # it will still empty the group (so this can be ignored).
            if e.response["error"] != "invalid_users":
                raise

    def chat_post_message(
        self,
        *,
        channel: str,
        text: str,
        thread_ts: str | None = None,
        icon_emoji: str | None = None,
        icon_url: str | None = None,
        username: str | None = None,
    ) -> ChatPostMessageResponse:
        """Post a message to a Slack channel.

        Resolves channel name to ID via cached channels, resolves any
        "@handle" mentions in `text` to working Slack mentions (see
        `_resolve_mentions`), then delegates to SlackApi.chat_post_message.
        Exceptions propagate to caller.

        Callers can write plain, natural mentions in `text` without knowing
        Slack's markup syntax or resolving IDs themselves, e.g.:
            chat_post_message(channel="alerts", text="Heads up @my-cluster-cluster!")
        becomes a real ping if "my-cluster-cluster" is a known usergroup handle
        or a user's org_username — otherwise the "@my-cluster-cluster" text is
        left as-is.

        Args:
            channel: Channel name (e.g., "sd-app-sre-reconcile")
            text: Message text, may contain "@handle" mentions
            thread_ts: Optional thread timestamp for replies
            icon_emoji: Emoji to use as the message icon (e.g., ":robot_face:")
            icon_url: URL to an image to use as the message icon
            username: Bot username to display

        Returns:
            ChatPostMessageResponse with ts, channel, thread_ts

        Raises:
            ValueError: If channel name is not found
        """
        channel_id = self._resolve_channel_id(channel)
        return self.slack_api.chat_post_message(
            channel_id=channel_id,
            text=self._resolve_mentions(text),
            thread_ts=thread_ts,
            icon_emoji=icon_emoji,
            icon_url=icon_url,
            username=username,
        )

    def _resolve_mentions(self, text: str) -> str:
        """Resolve "@handle" tokens in message text to working Slack mentions.

        For each "@handle" token (see `_MENTION_PATTERN`):
        - if `handle` matches a usergroup handle (checked first), replace with
          `<!subteam^{usergroup_id}>` — pings every member of that usergroup.
        - elif `handle` matches a user's org_username, replace with
          `<@{user_id}>` — pings that user.
        - otherwise leave the token unchanged (e.g. a typo, or an unrelated
          "@word" that isn't a real handle/username) — this is a no-op, not
          an error, since callers can't always know in advance whether a
          given handle exists.

        Uses the same cached `get_usergroups()`/`get_users()` data as the
        rest of this class, so this doesn't cost extra Slack API calls.
        """

        def replace(match: re.Match[str]) -> str:
            handle = match.group(1)
            if usergroup := self._get_usergroup_by_handle(handle):
                return f"<!subteam^{usergroup.id}>"
            for user in self.get_users().values():
                if user.org_username == handle:
                    return f"<@{user.id}>"
            logger.debug(
                f"Could not resolve mention '@{handle}' to a usergroup or user, "
                "leaving as plain text",
                handle=handle,
            )
            return match.group(0)

        return _MENTION_PATTERN.sub(replace, text)

    def get_flat_conversation_history(
        self,
        *,
        channel: str,
        from_timestamp: int,
        to_timestamp: int | None,
    ) -> list[SlackMessage]:
        """Get message history for a channel within a timestamp range.

        Resolves the channel name to ID via cached channels, then delegates to
        SlackApi.conversations_history, letting Slack filter by timestamp range
        server-side.

        Args:
            channel: Channel name (e.g., "sd-app-sre-reconcile")
            from_timestamp: Only return messages at or after this unix timestamp
            to_timestamp: Only return messages at or before this unix timestamp

        Returns:
            List of SlackMessage objects, newest first

        Raises:
            ValueError: If channel name is not found
        """
        channel_id = self._resolve_channel_id(channel)
        return self.slack_api.conversations_history(
            channel_id=channel_id,
            oldest=str(from_timestamp),
            latest=str(to_timestamp) if to_timestamp is not None else None,
        )

    def _resolve_user_id(self, org_username: str) -> str:
        """Resolve org_username to Slack user ID via cached users."""
        for user in self.get_users().values():
            if user.org_username == org_username:
                return user.id
        raise UserNotFoundError(f"User '{org_username}' not found")

    def send_dm(
        self,
        *,
        org_username: str,
        text: str,
    ) -> ChatPostMessageResponse:
        """Send a DM to a user by org_username.

        Resolves any "@handle" mentions in `text` first — see
        `chat_post_message`/`_resolve_mentions` for details.
        """
        user_id = self._resolve_user_id(org_username)
        dm_channel_id = self.slack_api.conversations_open(user_ids=[user_id])
        return self.slack_api.chat_post_message(
            channel_id=dm_channel_id, text=self._resolve_mentions(text)
        )

    def _resolve_channel_id(self, channel_name: str) -> str:
        """Resolve a channel name to its ID.

        Strips leading '#' if present (e.g., "#general" → "general").

        Args:
            channel_name: Channel name (e.g., "general" or "#general")

        Returns:
            Channel ID (e.g., "C01234ABCD")

        Raises:
            ValueError: If channel name is not found
        """
        channel_name = channel_name.lstrip("#")
        channels = self.get_channels()
        for ch in channels.values():
            if ch.name == channel_name:
                return ch.id
        raise ValueError(f"Channel '{channel_name}' not found")
