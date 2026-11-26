"""Shared exclusion for mutating IAM rotation CLI operations.

Reconcilers and manual IAM/Terraform writers must be paused separately. Locks
never expire automatically: a stopped process must be confirmed before removing
its orphaned lock, rather than allowing a slow writer to lose ownership.
"""

from __future__ import annotations

import sys
from contextlib import ExitStack, contextmanager
from hashlib import sha256
from typing import TYPE_CHECKING
from uuid import uuid4

from botocore.exceptions import BotoCoreError, ClientError

from reconcile.utils.state import State, init_state
from tools.rotate_erv2_cloudwatch_keys import RotationError

if TYPE_CHECKING:
    from collections.abc import Generator, Iterable

    from reconcile.utils.secret_reader import SecretReaderBase


def iam_user_scope(account_id: str, user: str) -> str:
    return f"iam/{account_id}/{sha256(user.encode()).hexdigest()}"


def terraform_state_scope(bucket: str, key: str) -> str:
    return "terraform/" + sha256(f"{bucket}\0{key}".encode()).hexdigest()


@contextmanager
def _lock(state: State, scope: str) -> Generator[None]:
    key = f"{state.state_path}/{scope}"
    try:
        response = state.client.put_object(
            Bucket=state.bucket,
            Key=key,
            Body=str(uuid4()).encode(),
            IfNoneMatch="*",
        )
    except ClientError as error:
        code = error.response.get("Error", {}).get("Code")
        if code in {"PreconditionFailed", "ConditionalRequestConflict", "412", "409"}:
            raise RotationError(
                f"Another rotation holds s3://{state.bucket}/{key}; no mutation attempted"
            ) from None
        raise RotationError(
            "Cannot acquire rotation lock; no mutation attempted"
        ) from None
    etag = response["ETag"]
    failed = False
    try:
        yield
    except BaseException:
        failed = True
        raise
    finally:
        # The unique body makes this ETag identify this owner's lock, including
        # when an operator incorrectly deletes/replaces a live lock.
        try:
            state.client.delete_object(Bucket=state.bucket, Key=key, IfMatch=etag)
        except BotoCoreError, ClientError:
            message = (
                f"Cannot release s3://{state.bucket}/{key}; inspect before retrying"
            )
            if failed:
                print(message, file=sys.stderr)
            else:
                raise RotationError(message) from None


@contextmanager
def operation_lock(
    reader: SecretReaderBase | None, scopes: Iterable[str]
) -> Generator[None]:
    with init_state("iam-key-rotation-locks", reader) as state, ExitStack() as stack:
        for scope in sorted(set(scopes)):
            stack.enter_context(_lock(state, scope))
        yield
