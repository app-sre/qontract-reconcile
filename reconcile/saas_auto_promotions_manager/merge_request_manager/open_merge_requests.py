from dataclasses import dataclass
from enum import Enum

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
