from enum import Enum


class FileSyncStatus(str, Enum):
    MR_CREATED = "mr_created"
    MR_EXISTS = "mr_exists"

    def __str__(self) -> str:
        return str(self.value)
