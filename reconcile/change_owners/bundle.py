from abc import abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import (
    Any,
    Optional,
    Protocol,
    Tuple,
)

from reconcile.utils.gql import get_diff


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


class FileDiffResolver(Protocol):
    """
    A protocol to lookup the diff of a file given its FileRef.
    """

    @abstractmethod
    def lookup_file_diff(
        self, file_ref: FileRef
    ) -> Tuple[Optional[dict[str, Any]], Optional[dict[str, Any]]]:
        ...


@dataclass
class QontractServerFileDiffResolver:
    """
    An implementation of the FileDiffResolver protocol that uses the comparison
    SHA from a qontract-server to lookup the diff of a file.
    """

    comparison_sha: str

    def lookup_file_diff(
        self, file_ref: FileRef
    ) -> Tuple[Optional[dict[str, Any]], Optional[dict[str, Any]]]:
        data = get_diff(
            old_sha=self.comparison_sha,
            file_type=file_ref.file_type.value,
            file_path=file_ref.path,
        )
        return data.get("old"), data.get("new")


class NoOpFileDiffResolver:
    """
    A resolver that is used in contexts where it is required from a typing
    perspective, but where the actual lookup is not needed.
    """

    def lookup_file_diff(
        self, file_ref: FileRef
    ) -> Tuple[Optional[dict[str, Any]], Optional[dict[str, Any]]]:
        raise Exception(
            "NoOpFileDiffResolver is not supposed to be used in "
            "runtime contexts where lookups are needed"
        )
