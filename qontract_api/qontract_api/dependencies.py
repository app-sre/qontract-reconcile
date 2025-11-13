"""Dependency injection container for qontract-api."""

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from qontract_api.auth import decode_token
from qontract_api.cache.base import CacheBackend
from qontract_api.models import User

security = HTTPBearer()


class Dependencies:
    """Global dependency container."""

    cache: CacheBackend | None = None


dependencies = Dependencies()


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
) -> User:
    """Get current user from JWT token."""
    try:
        token = credentials.credentials
        payload = decode_token(token)
        return User(username=payload.sub)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        ) from e
