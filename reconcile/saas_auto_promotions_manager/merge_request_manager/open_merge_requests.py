from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gitlab.v4.objects import ProjectMergeRequest


class MRKind(Enum):
    BATCHER = "batcher"
    SCHEDULER = "scheduler"


@dataclass
class OpenBatcherMergeRequest:
    raw: ProjectMergeRequest
    content_hashes: set[str]
    channels: set[str]
    failed_mr_check: bool
    is_batchable: bool


@dataclass
class OpenSchedulerMergeRequest:
    pass
