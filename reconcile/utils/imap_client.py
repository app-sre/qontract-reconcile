import imaplib

from reconcile.utils.secret_reader import SecretReader


class ImapClient:
    def __init__(self, settings):
        imap_config = self.get_imap_config(settings)
        self.host: str = imap_config["server"]
        self.user: str = imap_config["username"]
        self.password: str = imap_config["password"]
        self.port: int = int(imap_config["port"])
        self._server = None

    def __enter__(self):
        self._server = imaplib.IMAP4_SSL(host=self.host, port=self.port)
        self._server.login(self.user, self.password)
        return self

    def __exit__(self, *args, **kwargs):
        self._server.logout()

    @property
    def server(self):
        if self._server is None:
            raise Exception("Use ImapClient in with statement only!")
        return self._server

    @staticmethod
    def get_imap_config(settings):
        required_keys = ("server", "port", "username", "password")
        secret_reader = SecretReader(settings=settings)
        data = secret_reader.read_all(settings["imap"]["credentials"])
        try:
            config = {k: data[k] for k in required_keys}
        except KeyError as e:
            raise Exception(f"Missing expected IMAP config key in vault secret: {e}")
        return config

    def get_mails(self, folder: str = "INBOX", criteria: str = "ALL"):
        self.server.select(f'"{folder}"')
        _, data = self.server.uid("search", None, criteria)
        uids = list(data[0].split())
        results = []
        for uid in uids:
            _, data = self.server.uid("fetch", uid, "(RFC822)")
            msg = data[0][1].decode("utf-8")
            results.append({"uid": uid, "msg": msg})
        return results
