"""Dependency injection container for qontract-api."""

import contextlib
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from qontract_api.auth import decode_token
from qontract_api.cache.base import CacheBackend
from qontract_api.config import settings
from qontract_api.event_manager import EventManager
from qontract_api.logger import get_logger
from qontract_api.models import User
from qontract_api.opa import OPAClient, flatten_params
from qontract_api.secret_manager import SecretManager

logger = get_logger(__name__)
security = HTTPBearer()


def _authenticate(credentials: HTTPAuthorizationCredentials) -> User:
    """Authenticate: validate JWT token and return user."""
    try:
        payload = decode_token(credentials.credentials)
        if payload.sub in settings.jwt_revoked_subjects:
            logger.warning(f"Token subject '{payload.sub}' has been revoked")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has been revoked",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return User(username=payload.sub)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        ) from e


async def _authorize(request: Request, user: User) -> None:
    """Authorize: query OPA sidecar for parameter-level authorization."""
    opa_client: OPAClient | None = getattr(request.app.state, "opa_client", None)
    if opa_client is None:
        return

    if opa_client.should_skip(request.url.path):
        return

    params: dict[str, str] = {}
    params.update({k: str(v) for k, v in request.path_params.items()})
    params.update({k: str(v) for k, v in request.query_params.items()})

    with contextlib.suppress(Exception):
        body = await request.json()
        if isinstance(body, dict):
            params.update(flatten_params(body))

    route = request.scope.get("route")
    operation_id = getattr(route, "operation_id", None) or request.url.path

    request_id: str = getattr(request.state, "request_id", "")

    await opa_client.authorize(
        username=user.username,
        obj=operation_id,
        params=params,
        request_id=request_id,
    )


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
) -> User:
    """Authenticate and authorize the current user (authN + authZ)."""
    user = _authenticate(credentials)
    await _authorize(request, user)
    return user


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
