"""Secret backend factory for qontract-api."""

from qontract_api.secret_manager._base import SecretManager
from qontract_api.secret_manager._factory import get_secret_manager

__all__ = [
    "SecretManager",
    "get_secret_manager",
]
