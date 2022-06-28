import smtplib
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from typing import Any, Iterable, Union

from sretoolbox.utils import retry

from reconcile.utils.secret_reader import SecretReader


class SmtpClient:
    def __init__(self, settings: dict[str, Any]) -> None:
        smtp_config = self.get_smtp_config(settings)
        self.host: str = smtp_config["server"]
        self.port: int = int(smtp_config["port"])
        self.user: str = smtp_config["username"]
        self.passwd: str = smtp_config["password"]
        self.mail_address: str = settings["smtp"]["mailAddress"]
        self.timeout: int = settings["smtp"].get("timeout", 30)

        self._client: Union[smtplib.SMTP, None] = None

    @property
    def client(self) -> smtplib.SMTP:
        if self._client is None:
            self._client = smtplib.SMTP(
                host=self.host, port=self.port, timeout=self.timeout
            )
            self._client.send
            self._client.starttls()
            self._client.login(self.user, self.passwd)
        return self._client

    @staticmethod
    def get_smtp_config(settings: dict[str, Any]) -> dict[str, str]:
        config = {}
        required_keys = ("password", "port", "require_tls", "server", "username")
        secret_reader = SecretReader(settings=settings)
        data = secret_reader.read_all(settings["smtp"]["credentials"])
        try:
            for k in required_keys:
                config[k] = data[k]
        except KeyError as e:
            raise Exception(
                f"Missing expected SMTP config " f"key in vault secret: {e}"
            )
        return config

    def send_mails(self, mails: Iterable[tuple[str, str, str]]) -> None:
        for name, subject, body in mails:
            self.send_mail([name], subject, body)

    @retry()
    def send_mail(self, names: str, subject: str, body: str) -> None:
        msg = MIMEMultipart()
        from_name = str(Header("App SRE team automation", "utf-8"))
        msg["From"] = formataddr((from_name, self.user))
        to = set()
        for name in names:
            if "@" in name:
                to.add(name)
            else:
                to.add(f"{name}@{self.mail_address}")
        msg["To"] = ", ".join(to)
        msg["Subject"] = subject
        # add in the message body
        msg.attach(MIMEText(body, "plain"))
        self.client.sendmail(self.user, list(to), msg.as_string())

    def get_recipient(self, org_username: str) -> str:
        return f"{org_username}@{self.mail_address}"
