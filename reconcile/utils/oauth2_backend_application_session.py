import threading
from collections.abc import Mapping, MutableMapping
from typing import Any, Self

from oauthlib.oauth2 import BackendApplicationClient, TokenExpiredError
from requests import Response
from requests.adapters import BaseAdapter
from requests_oauthlib import OAuth2Session

FETCH_TOKEN_HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
    "Connection": "close",  # Close connection to avoid RemoteDisconnected ConnectionError
}


class OAuth2BackendApplicationSession:
    """
    OAuth2 session using Backend Application flow with auto and thread-safe token fetch.
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        token_url: str,
        scope: list[str] | None = None,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.token_url = token_url
        self.scope = scope
        client = BackendApplicationClient(client_id=client_id)
        self.session = OAuth2Session(client=client, scope=scope)
        self.token_lock = threading.Lock()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        self.close()

    def fetch_token(self) -> dict:
        """
        Fetch token from token_url and store it in the session.
        Thread-safe method to avoid multiple threads fetching the token at the same time.
        """
        token = self.session.token
        with self.token_lock:
            # Check if token is already fetched by another thread
            if token is not self.session.token:
                return self.session.token
            return self.session.fetch_token(
                token_url=self.token_url,
                client_id=self.client_id,
                client_secret=self.client_secret,
                scope=self.scope,
                headers=FETCH_TOKEN_HEADERS,
            )

    def request(
        self,
        method: str,
        url: str,
        data: Any = None,
        headers: Mapping[str, str] | None = None,
        withhold_token: bool = False,
        client_id: str | None = None,
        client_secret: str | None = None,
        **kwargs: Any,
    ) -> Response:
        """
        Make a request using OAuth2 session, compatible with the OAuth2Session.request method.
        Auto fetch token if never fetched before or if the token is expired.
        """
        if not self.session.authorized:
            self.fetch_token()
        try:
            return self.session.request(
                method=method,
                url=url,
                data=data,
                headers=headers,
                withhold_token=withhold_token,
                client_id=client_id,
                client_secret=client_secret,
                **kwargs,
            )
        except TokenExpiredError:
            self.fetch_token()
            return self.session.request(
                method=method,
                url=url,
                data=data,
                headers=headers,
                withhold_token=withhold_token,
                client_id=client_id,
                client_secret=client_secret,
                **kwargs,
            )

    # Delegates for ApiBase

    def close(self) -> None:
        self.session.close()

    def mount(self, prefix: str, adapter: BaseAdapter) -> None:
        self.session.mount(prefix, adapter)

    @property
    def headers(self) -> MutableMapping:
        return self.session.headers

    @property
    def auth(self) -> Any:
        return self.session.auth

    @auth.setter
    def auth(self, value: Any) -> None:
        self.session.auth = value

    def get(self, url: str, **kwargs: Any) -> Response:
        return self.session.get(url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> Response:
        return self.session.post(url, **kwargs)

    def put(self, url: str, **kwargs: Any) -> Response:
        return self.session.put(url, **kwargs)

    def delete(self, url: str, **kwargs: Any) -> Response:
        return self.session.delete(url, **kwargs)
