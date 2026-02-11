"""Dependency injection container for qontract-api."""

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from qontract_api.auth import decode_token
from qontract_api.cache.base import CacheBackend
from qontract_api.event_manager import EventManager
from qontract_api.models import User
from qontract_api.secret_manager import SecretManager

security = HTTPBearer()


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


def get_cache(request: Request) -> CacheBackend:
    """Get cache backend from app state.

    Args:
        request: FastAPI request object

    Returns:
        CacheBackend instance

    Raises:
        HTTPException: If cache backend is not available
    """
    cache = getattr(request.app.state, "cache", None)
    if cache is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Cache backend not available",
        )
    return cache


def get_secret_manager(request: Request) -> SecretManager:
    """Get secret backend from app state.

    Args:
        request: FastAPI request object
    Returns:
        SecretBackend instance
    Raises:
        HTTPException: If secret backend is not available
    """
    secret_manager = getattr(request.app.state, "secret_manager", None)
    if secret_manager is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Secret backend not available",
        )
    return secret_manager


def get_event_manager(request: Request) -> EventManager | None:
    """Get event manager from app state.

    Returns None if event publishing is disabled.
    """
    return getattr(request.app.state, "event_manager", None)


# Type aliases for dependency injection
CacheDep = Annotated[CacheBackend, Depends(get_cache)]
UserDep = Annotated[User, Depends(get_current_user)]
SecretManagerDep = Annotated[SecretManager, Depends(get_secret_manager)]
EventManagerDep = Annotated[EventManager | None, Depends(get_event_manager)]
