"""Tests for JWT authentication."""

from datetime import timedelta

import pytest
from jose import jwt

from qontract_api.auth import create_access_token, decode_token
from qontract_api.config import settings
from qontract_api.models import TokenData


def test_create_access_token() -> None:
    """Test JWT token creation."""
    token_data = TokenData(sub="testuser")
    token = create_access_token(data=token_data)

    assert isinstance(token, str)
    assert len(token) > 0

    # Decode to verify structure
    payload = jwt.decode(
        token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
    )
    assert payload["sub"] == "testuser"
    assert "exp" in payload


def test_create_access_token_custom_expiry() -> None:
    """Test JWT token creation with custom expiry."""
    token_data = TokenData(sub="testuser")
    expires_delta = timedelta(days=7)
    token = create_access_token(data=token_data, expires_delta=expires_delta)

    assert isinstance(token, str)


def test_decode_token() -> None:
    """Test JWT token decoding."""
    token_data = TokenData(sub="testuser")
    token = create_access_token(data=token_data)

    payload = decode_token(token)
    assert payload.sub == "testuser"
    assert payload.exp > 0


def test_decode_invalid_token() -> None:
    """Test decoding invalid token raises ValueError."""
    with pytest.raises(ValueError, match="Invalid token"):
        decode_token("invalid.token.here")


def test_decode_token_wrong_signature() -> None:
    """Test decoding token with wrong signature raises ValueError."""
    # Create a token with invalid signature
    with pytest.raises(ValueError, match="Invalid token"):
        decode_token(
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ0ZXN0In0.invalid_signature"
        )
