from typing import Any
from reconcile.utils.secret_reader import (
    HasSecret,
    SecretReaderBase,
)

from sretoolbox.utils import retry
from requests import (
    Session,
)


REQUEST_TIMEOUT_SEC = 60


class DynatraceBaseClient:
    """
    Thin client for Dynatrace. This class takes care of authentication
    and provides methods for GET, POST, PUT, DELETE to interact with the Dynatrace API.
    """

    def __init__(
        self,
        url: str,
        api_token: str,
    ):
        self._url = url
        self._api_token = api_token
        self._session = Session()
        self._session.headers.update(
            {
                "Authorization": f"Api-Token {self._api_token}",
                "Content-Type": "application/json",
            }
        )


    @retry()
    def get(self, path: str) -> Any:
        r = self._session.get(f"{self._url}{path}")
        r.raise_for_status()
        return r.json()

        # TODO: #from reconcile.utils.metrics import ocm_request


def init_dynatrace_base_client(
    url: str,
    api_token: HasSecret,
    secret_reader: SecretReaderBase,
) -> DynatraceBaseClient:
    """
    Initiate an API client towards a Dynatrace Environment.
    """
    return DynatraceBaseClient(
        url=url,
        api_token=secret_reader.read_secret(api_token),
    )
