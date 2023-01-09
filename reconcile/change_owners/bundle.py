from dataclasses import dataclass
from enum import Enum
from typing import Optional


class BundleFileType(Enum):
    DATAFILE = "datafile"
    RESOURCEFILE = "resourcefile"


@dataclass(frozen=True)
class FileRef:
    file_type: BundleFileType
    path: str
    schema: Optional[str]

    def __str__(self) -> str:
        return f"{self.file_type.value}:{self.path}"
