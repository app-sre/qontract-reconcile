"""AWS workspace client — Layer 2 (Cache + Compute).

Wraps AWSApi (Layer 1) with caching for expensive operations
and role assumption management. All caching is transparent to callers.
"""

import random
from collections.abc import Iterable, Mapping
from typing import Self

from qontract_utils.aws_api_typed.account import OptStatus, Region
from qontract_utils.aws_api_typed.api import AWSApi
from qontract_utils.aws_api_typed.iam import (
    AWSAccessKey,
    AWSEntityAlreadyExistsError,
    AWSLimitExceededError,
    AWSUser,
)
from qontract_utils.aws_api_typed.organization import (
    AWSAccount,
    AwsOrganizationOU,
)
from qontract_utils.aws_api_typed.service_quotas import (
    AWSQuota,
    AWSRequestedServiceQuotaChange,
    AWSResourceAlreadyExistsError,
)
from qontract_utils.aws_api_typed.support import AWSCase, SupportPlan
from qontract_utils.json_utils import json_dumps, json_loads

from qontract_api.cache import CacheBackend
from qontract_api.config import Settings
from qontract_api.logger import get_logger

logger = get_logger(__name__)

CACHE_PREFIX = "aws-account-manager"
CACHE_TTL = 86400  # 24h — idempotent ops (tags, OU, alias, regions)
CACHE_TTL_DURABLE = 604800  # 7 days — non-idempotent ops (create, support, quotas)
CACHE_TTL_JITTER_PERCENT = 10  # ±10% jitter to prevent cache stampede


class AWSWorkspaceClient:
    """Layer 2 workspace client for AWS operations.

    Wraps AWSApi with transparent caching and role assumption.
    Callers never need to know about caching — read methods return
    cached state, write methods update cache after AWS calls.
    """

    def __init__(
        self,
        *,
        aws_api: AWSApi,
        cache: CacheBackend,
        settings: Settings,
    ) -> None:
        self._aws_api = aws_api
        self._cache = cache
        self._settings = settings

    # --- Cache helpers (private) ---

    @staticmethod
    def _cache_key(*parts: str) -> str:
        """Build a cache key from parts."""
        return f"{CACHE_PREFIX}:{':'.join(parts)}"

    @staticmethod
    def _ttl_with_jitter(base_ttl: int) -> int:
        """Add jitter to TTL to prevent cache stampede after Redis restart."""
        jitter = base_ttl * CACHE_TTL_JITTER_PERCENT // 100
        return base_ttl + random.randint(-jitter, jitter)  # noqa: S311

    def _cache_get(self, *parts: str) -> str | None:
        """Get a cached string value."""
        return self._cache.get(self._cache_key(*parts))

    def _cache_set(self, *parts: str, value: str) -> None:
        """Set a cached string value (with distributed lock and jitter)."""
        key = self._cache_key(*parts)
        with self._cache.lock(key):
            self._cache.set(key, value, self._ttl_with_jitter(CACHE_TTL))

    def _cache_set_durable(self, *parts: str, value: str) -> None:
        """Set a cached string value with extended TTL for non-idempotent operations."""
        key = self._cache_key(*parts)
        with self._cache.lock(key):
            self._cache.set(key, value, self._ttl_with_jitter(CACHE_TTL_DURABLE))

    # --- Cached reads (cache hit → return; cache miss → fetch from AWS, cache, return) ---

    def get_tags(self, account_name: str, *, uid: str) -> dict[str, str]:
        """Get current tags. Returns cached value or fetches from AWS on miss."""
        if value := self._cache_get(account_name, "tags"):
            return json_loads(value)
        tags = self._aws_api.organizations.list_tags_for_resource(resource_id=uid)
        self._cache_set(account_name, "tags", value=json_dumps(tags))
        return tags

    def get_account_ou(
        self,
        account_name: str,
        *,
        uid: str,
        payer_name: str | None = None,
    ) -> str:
        """Get current OU path. Returns cached value or resolves from AWS on miss."""
        if cached := self._cache_get(account_name, "ou"):
            return cached
        parent_ou_id = self._aws_api.organizations.get_ou(uid=uid)
        tree = self.get_organizational_units_tree(payer_name=payer_name)
        if ou_path := tree.find_path_by_id(parent_ou_id):
            self._cache_set(account_name, "ou", value=ou_path)
            return ou_path
        raise RuntimeError(
            f"{account_name}: Could not resolve OU path for parent {parent_ou_id}",
        )

    def get_account_alias_cached(self, account_name: str) -> str | None:
        """Get current account alias. Returns cached value or fetches from AWS on miss."""
        if cached := self._cache_get(account_name, "alias"):
            return cached
        if alias := self._aws_api.iam.get_account_alias():
            self._cache_set(account_name, "alias", value=alias)
        return alias

    def get_applied_quotas(
        self,
        account_name: str,
        *,
        desired_quotas: Iterable[tuple[str, str, float]],
    ) -> str:
        """Get current quotas config. Returns cached or fetches from AWS on miss.

        Args:
            account_name: Account name for cache key
            desired_quotas: Iterable of (service_code, quota_code, desired_value)
                used to know which quotas to fetch on cache miss
        """
        if cached := self._cache_get(account_name, "quotas"):
            return cached
        current = json_dumps([
            {
                "sc": sc,
                "qc": qc,
                "v": self._aws_api.service_quotas.get_service_quota(
                    service_code=sc,
                    quota_code=qc,
                ).value,
            }
            for sc, qc, _ in desired_quotas
        ])
        self._cache_set(account_name, "quotas", value=current)
        return current

    def get_applied_security_contact(self, account_name: str) -> str | None:
        """Get current security contact. Returns cached or fetches from AWS on miss."""
        if cached := self._cache_get(account_name, "security_contact"):
            return cached
        contact = self._aws_api.account.get_security_contact()
        if not contact:
            return None
        value = json_dumps({
            "name": contact["Name"],
            "title": contact["Title"],
            "email": contact["EmailAddress"],
            "phone_number": contact["PhoneNumber"],
        })
        self._cache_set(account_name, "security_contact", value=value)
        return value

    def get_applied_regions(self, account_name: str) -> list[str]:
        """Get current enabled regions. Returns cached or fetches from AWS on miss."""
        if value := self._cache_get(account_name, "regions"):
            return json_loads(value)
        regions = sorted(
            r.name
            for r in self._aws_api.account.list_regions()
            if r.status in {OptStatus.ENABLED, OptStatus.ENABLED_BY_DEFAULT}
        )
        self._cache_set(account_name, "regions", value=json_dumps(regions))
        return regions

    # --- Organization operations ---

    def create_account(
        self,
        *,
        account_name: str,
        email: str,
        name: str,
    ) -> str | None:
        """Create an organization account. Returns request ID (cached)."""
        if cached := self._cache_get(account_name, "create_account"):
            return cached

        status = self._aws_api.organizations.create_account(email=email, name=name)
        self._cache_set_durable(account_name, "create_account", value=status.id)
        return status.id

    def describe_create_account_status(
        self,
        *,
        account_name: str,
        request_id: str,
    ) -> str | None:
        """Check account creation status. Returns UID if ready, None if in progress (cached).

        Raises RuntimeError on failure or unexpected state.
        """
        if cached := self._cache_get(account_name, "describe_account"):
            return cached

        status = self._aws_api.organizations.describe_create_account_status(
            create_account_request_id=request_id,
        )
        match status.state:
            case "SUCCEEDED":
                if not status.uid:
                    raise RuntimeError(
                        "Account creation succeeded but no account ID returned",
                    )
                self._cache_set_durable(
                    account_name, "describe_account", value=status.uid
                )
                return status.uid
            case "FAILED":
                raise RuntimeError(f"Account creation failed: {status.failure_reason}")
            case "IN_PROGRESS":
                return None
            case _:
                raise RuntimeError(
                    f"Unexpected account creation status: {status.state}",
                )

    def get_organizational_units_tree(
        self,
        *,
        payer_name: str | None = None,
    ) -> AwsOrganizationOU:
        """Get OU tree (cached in Redis per payer account).

        Falls back to Layer 1 lru_cache if no payer_name is provided.
        When payer_name is set, the tree is cached in Redis so it can be
        shared across Celery tasks that process different accounts under
        the same payer.
        """
        if payer_name:
            if cached := self._cache_get("ou-tree", payer_name):
                return AwsOrganizationOU.model_validate_json(cached)
            tree = self._aws_api.organizations.get_organizational_units_tree()
            self._cache_set("ou-tree", payer_name, value=tree.model_dump_json())
            return tree
        return self._aws_api.organizations.get_organizational_units_tree()

    def tag_account(
        self,
        *,
        account_name: str,
        uid: str,
        tags: Mapping[str, str],
    ) -> None:
        """Tag an account and update cache."""
        self._aws_api.organizations.tag_resource(resource_id=uid, tags=tags)
        self._cache_set(account_name, "tags", value=json_dumps(dict(tags)))

    def untag_account(self, *, uid: str, tag_keys: Iterable[str]) -> None:
        """Remove tags from an account."""
        self._aws_api.organizations.untag_resource(resource_id=uid, tag_keys=tag_keys)

    def move_account(
        self,
        *,
        account_name: str,
        uid: str,
        destination_ou_path: str,
        payer_name: str | None = None,
    ) -> None:
        """Move account to a destination OU by path and update cache."""
        org_tree = self.get_organizational_units_tree(payer_name=payer_name)
        destination = org_tree.find(destination_ou_path)
        self._aws_api.organizations.move_account(
            uid=uid,
            destination_parent_id=destination.id,
        )
        self._cache_set(account_name, "ou", value=destination_ou_path)

    def describe_account(self, *, uid: str) -> AWSAccount:
        """Describe an account."""
        return self._aws_api.organizations.describe_account(uid=uid)

    # --- IAM operations ---

    def create_user(self, *, account_name: str, user_name: str) -> AWSUser | None:
        """Create an IAM user (cached — returns None if already created).

        Handles cache expiry gracefully: if the user already exists in AWS
        but the cache entry expired, catches the error, re-caches, and
        returns None.
        """
        if self._cache_get(account_name, "iam_user", user_name) is not None:
            return None

        try:
            user = self._aws_api.iam.create_user(user_name=user_name)
        except AWSEntityAlreadyExistsError:
            logger.info(
                "%s: IAM user '%s' already exists, re-caching",
                account_name,
                user_name,
            )
            self._cache_set_durable(
                account_name, "iam_user", user_name, value=user_name
            )
            return None
        self._cache_set_durable(account_name, "iam_user", user_name, value=user_name)
        return user

    def attach_user_policy(self, *, user_name: str, policy_arn: str) -> None:
        """Attach a policy to a user."""
        self._aws_api.iam.attach_user_policy(user_name=user_name, policy_arn=policy_arn)

    def create_access_key(
        self,
        *,
        account_name: str,
        user_name: str,
    ) -> AWSAccessKey:
        """Create an access key for a user (cached).

        If cached from a previous run, returns the cached key.
        If AWS returns LimitExceeded (max 2 keys), deletes all existing keys
        and creates a fresh one — this handles the crash-after-create scenario.
        """
        if cached := self._cache_get(account_name, "access_key", user_name):
            data = json_loads(cached)
            return AWSAccessKey(
                AccessKeyId=data["access_key_id"],
                SecretAccessKey=data["secret_access_key"],
            )

        try:
            key = self._aws_api.iam.create_access_key(user_name=user_name)
        except AWSLimitExceededError:
            raise RuntimeError(
                f"IAM user '{user_name}' in account '{account_name}' already has the "
                "maximum number of access keys. Manual cleanup required.",
            ) from None

        self._cache_set_durable(
            account_name,
            "access_key",
            user_name,
            value=json_dumps({
                "access_key_id": key.access_key_id,
                "secret_access_key": key.secret_access_key,
            }),
        )
        return key

    def set_account_alias(self, *, account_name: str, alias: str) -> None:
        """Set the account alias and update cache."""
        self._aws_api.iam.set_account_alias(account_alias=alias)
        self._cache_set(account_name, "alias", value=alias)

    # --- Service quotas ---

    def get_service_quota(self, *, service_code: str, quota_code: str) -> AWSQuota:
        """Get a service quota value."""
        return self._aws_api.service_quotas.get_service_quota(
            service_code=service_code,
            quota_code=quota_code,
        )

    def apply_quota_changes(
        self,
        *,
        account_name: str,
        changes: Iterable[tuple[str, str, float]],
        desired_json: str,
    ) -> list[str]:
        """Request quota changes and cache desired config. Returns request IDs.

        Catches ``AWSResourceAlreadyExistsError`` per-quota so that a single
        pending request does not block the entire reconcile task. When any
        quota has a pending request, the cache is NOT updated so the
        operation retries on the next run.
        """
        has_pending = False
        request_ids: list[str] = []
        for service_code, quota_code, desired_value in changes:
            try:
                result = self._aws_api.service_quotas.request_service_quota_change(
                    service_code=service_code,
                    quota_code=quota_code,
                    desired_value=desired_value,
                )
                request_ids.append(result.id)
            except AWSResourceAlreadyExistsError:
                logger.warning(
                    "Quota %s/%s already has a pending request, skipping",
                    service_code,
                    quota_code,
                )
                has_pending = True
        if not has_pending:
            self._cache_set(account_name, "quotas", value=desired_json)
        if request_ids:
            self._cache_set_durable(
                account_name,
                "quota_request_ids",
                value=json_dumps(request_ids),
            )
        return request_ids

    def get_quota_request_ids(self, account_name: str) -> list[str]:
        """Get cached quota request IDs for status tracking."""
        if cached := self._cache_get(account_name, "quota_request_ids"):
            return json_loads(cached)
        return []

    def clear_quota_request_ids(self, account_name: str) -> None:
        """Clear cached quota request IDs after all are resolved."""
        self._cache.delete(self._cache_key(account_name, "quota_request_ids"))

    def get_requested_service_quota_change(
        self,
        *,
        request_id: str,
    ) -> AWSRequestedServiceQuotaChange:
        """Get status of a quota change request."""
        return self._aws_api.service_quotas.get_requested_service_quota_change(
            request_id=request_id,
        )

    # --- Support ---

    def get_support_level(self, account_name: str) -> SupportPlan:
        """Get the support level for the account (cached)."""
        if self._cache_get(account_name, "enterprise_support") == "enabled":
            return SupportPlan.ENTERPRISE

        level = self._aws_api.support.get_support_level()
        if level == SupportPlan.ENTERPRISE:
            self._cache_set(account_name, "enterprise_support", value="enabled")
        return level

    def get_support_case_id(self, account_name: str, *, subject: str) -> str | None:
        """Get support case ID from cache, falling back to AWS if cache lost."""
        if cached := self._cache_get(account_name, "support_case_id"):
            return cached

        # Cache miss — check AWS for existing open cases to prevent duplicates
        open_cases = self._aws_api.support.find_open_cases(subject_contains=subject)
        if open_cases:
            case_id = open_cases[0].case_id
            logger.info(
                "Found existing open support case from AWS (cache was lost)",
                account_name=account_name,
                case_id=case_id,
            )
            self._cache_set_durable(account_name, "support_case_id", value=case_id)
            return case_id

        return None

    def create_support_case(
        self,
        *,
        account_name: str,
        subject: str,
        message: str,
    ) -> str:
        """Create a support case, cache the case ID, and return it."""
        case_id = self._aws_api.support.create_case(subject=subject, message=message)
        self._cache_set_durable(account_name, "support_case_id", value=case_id)
        return case_id

    def describe_support_case(self, *, case_id: str) -> AWSCase:
        """Describe a support case."""
        return self._aws_api.support.describe_case(case_id=case_id)

    # --- Account operations ---

    def set_security_contact(
        self,
        *,
        account_name: str,
        name: str,
        title: str,
        email: str,
        phone_number: str,
    ) -> None:
        """Set the security contact for the account and update cache."""
        self._aws_api.account.set_security_contact(
            name=name,
            title=title,
            email=email,
            phone_number=phone_number,
        )
        self._cache_set(
            account_name,
            "security_contact",
            value=json_dumps({
                "name": name,
                "title": title,
                "email": email,
                "phone_number": phone_number,
            }),
        )

    def list_regions(self) -> list[Region]:
        """List all regions with their status."""
        return self._aws_api.account.list_regions()

    def apply_region_changes(
        self,
        *,
        account_name: str,
        to_enable: Iterable[str],
        to_disable: Iterable[str],
        desired: list[str],
    ) -> None:
        """Enable/disable regions and cache desired config."""
        for region in to_enable:
            self._aws_api.account.enable_region(region)
        for region in to_disable:
            self._aws_api.account.disable_region(region)
        self._cache_set(account_name, "regions", value=json_dumps(desired))

    # --- Role assumption ---

    def assume_role(self, *, account_id: str, role: str) -> "AWSWorkspaceClient":
        """Assume a role in another account, returning a new workspace client.

        The caller is responsible for closing the returned client.
        """
        role_api = self._aws_api.assume_role(account_id=account_id, role=role)
        return AWSWorkspaceClient(
            aws_api=role_api,
            cache=self._cache,
            settings=self._settings,
        )

    def close(self) -> None:
        """Close the underlying AWS API client."""
        self._aws_api.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
