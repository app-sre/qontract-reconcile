from enum import Enum


class ClusterType(Enum):
    OSD = "osd"
    ROSA_CLASSIC = "rosa"
    ROSA_HCP = "hypershift"
