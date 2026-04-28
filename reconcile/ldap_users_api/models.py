from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


class PathType(StrEnum):
    USER = "user"
    REQUEST = "request"
    QUERY = "query"
    GABI = "gabi"
    AWS_ACCOUNTS = "aws_accounts"
    SCHEDULE = "schedule"
    SRE_CHECKPOINT = "sre_checkpoint"


class PathSpec(BaseModel, frozen=True):
    type: PathType
    path: str

    @field_validator("path")
    @classmethod
    def prepend_data_to_path(cls, v: str) -> str:
        normalized = v.strip()
        if normalized == "data" or normalized.startswith("data/"):
            return normalized
        return f"data/{normalized.lstrip('/')}"


class UserPaths(BaseModel, frozen=True):
    username: str
    paths: list[PathSpec] = Field(default_factory=list)

    @property
    def delete_file_paths(self) -> list[PathSpec]:
        """Return paths with type USER/REQUEST/QUERY that should be deleted."""
        return [
            p
            for p in self.paths
            if p.type
            in {
                PathType.USER,
                PathType.REQUEST,
                PathType.QUERY,
                PathType.SRE_CHECKPOINT,
            }
        ]

    @property
    def modify_file_paths(self) -> list[PathSpec]:
        """Return paths with type GABI/AWS_ACCOUNTS/SCHEDULE that should be modified."""
        return [
            p
            for p in self.paths
            if p.type in {PathType.GABI, PathType.AWS_ACCOUNTS, PathType.SCHEDULE}
        ]
