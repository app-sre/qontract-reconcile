from typing import Any


class ElasticSearchResourceNameInvalidError(Exception):
    def __init__(self, msg: Any) -> None:
        super().__init__(str(msg))


class ElasticSearchResourceMissingSubnetIdError(Exception):
    def __init__(self, msg: Any) -> None:
        super().__init__(str(msg))


class ElasticSearchResourceZoneAwareSubnetInvalidError(Exception):
    def __init__(self, msg: Any) -> None:
        super().__init__(str(msg))


class ElasticSearchResourceColdStorageError(Exception):
    def __init__(self, msg: Any) -> None:
        super().__init__(str(msg))
