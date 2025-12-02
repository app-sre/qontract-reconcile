"""Token Bucket rate limiting algorithm with cache backend abstraction."""

import logging
import time
from threading import Lock

from pydantic import BaseModel

from qontract_api.cache import CacheBackend
from qontract_api.rate_limit.exceptions import RateLimitExceeded

logger = logging.getLogger(__name__)


class TokenBucketState(BaseModel):
    """Token bucket state stored in cache."""

    tokens: float
    last_refill_time: float


class TokenBucket:
    """
    Token Bucket rate limiter with cache-backed distributed state.

    The token bucket algorithm allows for burst traffic up to the bucket capacity
    while maintaining a sustained throughput based on the refill rate.

    Uses the cache abstraction (Redis, DynamoDB, etc.) for distributed state storage,
    enabling rate limiting across multiple API instances.

    Attributes:
        cache: Cache backend for distributed state storage (abstract)
        bucket_name: Unique identifier for this rate limit bucket
        capacity: Maximum number of tokens in the bucket
        refill_rate: Number of tokens added per second
    """

    def __init__(
        self,
        cache: CacheBackend,
        bucket_name: str,
        capacity: int,
        refill_rate: float,
    ) -> None:
        """
        Initialize Token Bucket rate limiter.

        Args:
            cache: Cache backend for storing bucket state
            bucket_name: Unique bucket identifier (e.g., "slack:tier2")
            capacity: Maximum tokens in bucket (burst capacity)
            refill_rate: Tokens added per second (sustained rate)
        """
        self.cache = cache
        self.bucket_name = bucket_name
        self.capacity = capacity
        self.refill_rate = refill_rate
        self._sync_lock = Lock()

    def acquire(self, tokens: int = 1, timeout: float = 30) -> None:
        """
        Acquire tokens from bucket (blocking with timeout).

        This is a synchronous blocking call that will wait until tokens are available
        or the timeout is reached. Uses a thread lock for thread-safety.

        Args:
            tokens: Number of tokens to acquire (default: 1)
            timeout: Maximum time to wait in seconds (default: 30)

        Raises:
            RateLimitExceeded: If tokens not available within timeout period
        """
        logger.debug(
            "Acquiring %d token(s) from bucket '%s' (timeout=%.1fs)",
            tokens,
            self.bucket_name,
            timeout,
        )

        with self._sync_lock:
            start_time = time.time()

            while True:
                current_tokens = self._refill_tokens()
                logger.debug(
                    "Bucket '%s' has %.2f tokens available (requested: %d)",
                    self.bucket_name,
                    current_tokens,
                    tokens,
                )

                if current_tokens >= tokens:
                    # Enough tokens available - consume them
                    remaining_tokens = current_tokens - tokens
                    self._update_bucket_state(remaining_tokens, time.time())
                    logger.debug(
                        "Acquired %d token(s) from bucket '%s' (%.2f tokens remaining)",
                        tokens,
                        self.bucket_name,
                        remaining_tokens,
                    )
                    return

                # Not enough tokens - check timeout
                elapsed = time.time() - start_time
                if elapsed >= timeout:
                    logger.debug(
                        "Rate limit timeout for bucket '%s': requested %d tokens, "
                        "only %.2f available after %.1fs",
                        self.bucket_name,
                        tokens,
                        current_tokens,
                        elapsed,
                    )
                    raise RateLimitExceeded(
                        f"Rate limit exceeded for {self.bucket_name}: "
                        f"requested {tokens} tokens, only {current_tokens:.2f} available"
                    )

                # Calculate wait time
                tokens_needed = tokens - current_tokens
                wait_time = min(
                    tokens_needed / self.refill_rate,  # Time to refill needed tokens
                    timeout - elapsed,  # Remaining timeout
                    1.0,  # Max 1 second per iteration
                )

                logger.debug(
                    "Bucket '%s' waiting %.2fs for %.2f tokens to refill (rate=%.2f/s)",
                    self.bucket_name,
                    wait_time,
                    tokens_needed,
                    self.refill_rate,
                )
                time.sleep(wait_time)

    def _refill_tokens(self) -> float:
        """
        Calculate current token count with refill.

        Uses cache backend to fetch last state and calculate how many tokens
        should be added based on elapsed time and refill rate.

        Returns:
            Current number of tokens in bucket (capped at capacity)
        """
        # Get current bucket state from cache
        state = self._get_bucket_state()
        last_tokens = state.tokens
        last_refill_time = state.last_refill_time

        # Calculate tokens to add based on elapsed time
        now = time.time()
        elapsed = now - last_refill_time
        tokens_to_add = elapsed * self.refill_rate

        # Calculate new token count (capped at capacity)
        new_tokens = min(last_tokens + tokens_to_add, self.capacity)

        logger.debug(
            "Refilling bucket '%s': %.2f tokens + (%.2fs x %.2f/s) = %.2f tokens (cap: %d)",
            self.bucket_name,
            last_tokens,
            elapsed,
            self.refill_rate,
            new_tokens,
            self.capacity,
        )

        return new_tokens

    def _get_bucket_state(self) -> TokenBucketState:
        """
        Get bucket state from cache.

        Uses CacheBackend.get_obj() for synchronous cache access with Pydantic model (ADR-005).

        Returns:
            TokenBucketState with current bucket state or initial state if not cached
        """
        cache_key = f"rate_limit:{self.bucket_name}:state"

        # Get cached value using sync method (follows ADR-005)
        cached_state = self.cache.get_obj(cache_key, cls=TokenBucketState)

        if cached_state:
            return cached_state

        # No cached state - return initial state (bucket is full)
        return TokenBucketState(
            tokens=self.capacity,
            last_refill_time=time.time(),
        )

    def _update_bucket_state(self, new_tokens: float, refill_time: float) -> None:
        """
        Update bucket state in cache.

        Uses CacheBackend.set_obj() for synchronous cache access with Pydantic model (ADR-005).

        Args:
            new_tokens: New token count
            refill_time: Timestamp of last refill
        """
        cache_key = f"rate_limit:{self.bucket_name}:state"
        state = TokenBucketState(
            tokens=new_tokens,
            last_refill_time=refill_time,
        )

        # TTL: 2x capacity / refill_rate (time to fully refill bucket twice)
        ttl = int((self.capacity / self.refill_rate) * 2)

        logger.debug(
            "Updating bucket '%s' state: %.2f tokens (TTL: %ds)",
            self.bucket_name,
            new_tokens,
            ttl,
        )

        # Update cache using sync method (follows ADR-005)
        self.cache.set_obj(cache_key, state, ttl=ttl)
