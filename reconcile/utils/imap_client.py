import imaplib
from typing import Any, Union

from reconcile.utils.secret_reader import SecretReader


class ImapClient:
    def __init__(self, settings: dict[str, Any]) -> None:
        imap_config = self.get_imap_config(settings)
        self.host: str = imap_config["server"]
        self.user: str = imap_config["username"]
        self.password: str = imap_config["password"]
        self.port: int = int(imap_config["port"])
        self.timeout: int = settings["imap"].get("timeout", 30)
        self._server: Union[imaplib.IMAP4_SSL, None] = None

    def __enter__(self) -> "ImapClient":
        self._server = imaplib.IMAP4_SSL(
            host=self.host, port=self.port, timeout=self.timeout
        )
        self._server.login(self.user, self.password)
        return self

    def __exit__(self, *args, **kwargs) -> None:
        if self._server:
            self._server.logout()

    @staticmethod
    def get_imap_config(settings: dict[str, Any]) -> dict[str, str]:
        required_keys = ("server", "port", "username", "password")
        secret_reader = SecretReader(settings=settings)
        data = secret_reader.read_all(settings["imap"]["credentials"])
        try:
            config = {k: data[k] for k in required_keys}
        except KeyError as e:
            raise Exception(f"Missing expected IMAP config key in vault secret: {e}")
        return config

    def get_mails(
        self, folder: str = "INBOX", criteria: str = "ALL"
    ) -> list[dict[str, str]]:
        if not self._server:
            raise Exception("Use ImapClient in with statement only!")

        self._server.select(f'"{folder}"')
        _, data = self._server.search(None, criteria)
        uids = list(data[0].split())
        results = []
        for uid in uids:
            _, data = self._server.uid("fetch", uid, "(RFC822)")
            msg = data[0][1].decode("utf-8")
            results.append({"uid": uid, "msg": msg})
        return results
