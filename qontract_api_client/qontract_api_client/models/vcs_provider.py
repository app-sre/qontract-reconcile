from enum import Enum


class VCSProvider(str, Enum):
    GITHUB = "github"
    GITLAB = "gitlab"

    def __str__(self) -> str:
        return str(self.value)
