from abc import (
    ABC,
    abstractmethod,
)
from dataclasses import dataclass


@dataclass(frozen=True)
class LabelOwnerRef(ABC):
    ocm_env: str
    label_container_href: str | None

    @abstractmethod
    def identity_labels(self) -> list[str]:
        pass

    def required_label_container_href(self) -> str:
        if self.label_container_href is None:
            raise ValueError(
                "label_container_href is missing - this method should probably not be called in this state"
            )
        return self.label_container_href


@dataclass(frozen=True)
class OrgRef(LabelOwnerRef):
    org_id: str
    name: str

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, OrgRef)
            and self.org_id == other.org_id
            and self.ocm_env == other.ocm_env
        )

    def __hash__(self) -> int:
        return hash((self.org_id, self.ocm_env))

    def identity_labels(self) -> list[str]:
        return [f"org_id={self.org_id}", f"org_name={self.name}"]


@dataclass(frozen=True)
class ClusterRef(LabelOwnerRef):
    cluster_id: str
    org_id: str
    name: str

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, ClusterRef)
            and self.cluster_id == other.cluster_id
            and self.org_id == other.org_id
            and self.ocm_env == other.ocm_env
        )

    def __hash__(self) -> int:
        return hash((self.cluster_id, self.org_id, self.ocm_env))

    def identity_labels(self) -> list[str]:
        return [
            f"org_id={self.org_id}",
            f"cluster_id={self.cluster_id}",
            f"cluster_name={self.name}",
        ]


LabelState = dict[LabelOwnerRef, dict[str, str]]


class LabelSource(ABC):
    @abstractmethod
    def get_labels(self) -> LabelState:
        pass
