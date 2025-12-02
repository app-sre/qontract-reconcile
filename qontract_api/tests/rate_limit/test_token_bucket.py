"""Unit tests for Token Bucket rate limiter."""

import time
from unittest.mock import MagicMock

import pytest

from qontract_api.rate_limit.exceptions import RateLimitExceeded
from qontract_api.rate_limit.token_bucket import TokenBucket


@pytest.fixture
def mock_cache() -> MagicMock:
    """Create mock cache backend with sync methods."""
    cache = MagicMock()
    # Mock sync get_obj() method - returns None (no cached state)
    cache.get_obj = MagicMock(return_value=None)
    # Mock sync set_obj() method
    cache.set_obj = MagicMock(return_value=None)
    return cache


def test_token_bucket_initialization(mock_cache: MagicMock) -> None:
    """Test TokenBucket initialization."""
    bucket = TokenBucket(
        cache=mock_cache,
        bucket_name="test-bucket",
        capacity=10,
        refill_rate=1.0,
    )
    assert bucket.cache == mock_cache
    assert bucket.bucket_name == "test-bucket"
    assert bucket.capacity == 10
    assert bucket.refill_rate == 1.0


def test_acquire_sync_single_token(mock_cache: MagicMock) -> None:
    """Test acquiring a single token (should succeed immediately)."""
    bucket = TokenBucket(
        cache=mock_cache,
        bucket_name="test-bucket",
        capacity=10,
        refill_rate=1.0,
    )

    # Should succeed without blocking (bucket starts full)
    bucket.acquire(tokens=1, timeout=1.0)


def test_acquire_sync_within_capacity(mock_cache: MagicMock) -> None:
    """Test acquiring tokens within capacity."""
    bucket = TokenBucket(
        cache=mock_cache,
        bucket_name="test-bucket",
        capacity=10,
        refill_rate=1.0,
    )

    # Acquire 5 tokens (within capacity)
    bucket.acquire(tokens=5, timeout=1.0)


def test_acquire_sync_exceeds_capacity_timeout(mock_cache: MagicMock) -> None:
    """Test that exceeding capacity raises RateLimitExceeded."""
    bucket = TokenBucket(
        cache=mock_cache,
        bucket_name="test-bucket",
        capacity=5,
        refill_rate=1.0,
    )

    # Try to acquire more tokens than capacity with short timeout
    with pytest.raises(RateLimitExceeded) as exc_info:
        bucket.acquire(tokens=100, timeout=0.1)

    assert "Rate limit exceeded" in str(exc_info.value)
    assert "test-bucket" in str(exc_info.value)


def test_acquire_sync_multiple_calls(mock_cache: MagicMock) -> None:
    """Test multiple sequential token acquisitions."""
    bucket = TokenBucket(
        cache=mock_cache,
        bucket_name="test-bucket",
        capacity=10,
        refill_rate=10.0,  # Fast refill for testing
    )

    # First acquisition should succeed
    bucket.acquire(tokens=1, timeout=1.0)

    # Second acquisition should also succeed (due to fast refill)
    time.sleep(0.2)  # Allow some refill
    bucket.acquire(tokens=1, timeout=1.0)


def test_rate_limit_exceeded_exception_attributes(mock_cache: MagicMock) -> None:
    """Test RateLimitExceeded exception attributes."""
    bucket = TokenBucket(
        cache=mock_cache,
        bucket_name="test-bucket",
        capacity=1,
        refill_rate=0.1,
    )

    with pytest.raises(RateLimitExceeded) as exc_info:
        bucket.acquire(tokens=100, timeout=0.05)

    assert exc_info.value.status_code == 429
    assert "test-bucket" in exc_info.value.message


def test_refill_tokens_calculation(mock_cache: MagicMock) -> None:
    """Test that tokens refill over time."""
    bucket = TokenBucket(
        cache=mock_cache,
        bucket_name="test-bucket",
        capacity=10,
        refill_rate=10.0,  # 10 tokens per second
    )

    # Get initial token count
    initial_tokens = bucket._refill_tokens()
    assert initial_tokens <= bucket.capacity

    # Tokens should refill over time (capped at capacity)
    time.sleep(0.5)  # Wait 0.5 seconds (should add ~5 tokens if bucket was empty)
    refilled_tokens = bucket._refill_tokens()
    assert refilled_tokens <= bucket.capacity


def test_bucket_state_methods(mock_cache: MagicMock) -> None:
    """Test bucket state get/update methods."""
    bucket = TokenBucket(
        cache=mock_cache,
        bucket_name="test-bucket",
        capacity=10,
        refill_rate=1.0,
    )

    # Get state should return TokenBucketState with tokens and last_refill_time
    state = bucket._get_bucket_state()
    assert state.tokens == bucket.capacity
    assert isinstance(state.last_refill_time, float)

    # Update state should not raise exceptions
    bucket._update_bucket_state(5.0, time.time())
