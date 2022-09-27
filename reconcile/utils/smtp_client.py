import smtplib
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from typing import Iterable, Optional
from pydantic import BaseModel

from sretoolbox.utils import retry

from reconcile.utils.secret_reader import SecretReader, SupportsSecret


class SmtpCredentials(BaseModel):
    server: str
    port: int
    username: str
    password: str
    # require_tls: bool - currently not in use


def get_smtp_credentials(
    secret_reader: SecretReader, secret: SupportsSecret
) -> SmtpCredentials:
    """Retrieve SMTP credentials from config or vault."""
    # This will change later when SecretReader fully supports 'SupportsSecret'
    data = secret_reader.read_all(
        {
            "path": secret.path,
            "field": secret.field,
            "format": secret.q_format,
            "version": secret.version,
        }
    )
    return SmtpCredentials(**data)


class SmtpClient:
    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        mail_address: str,
        timeout: int = 30,
    ) -> None:
        self.host = host
        self.port = port
        self.user = username
        self.passwd = password
        self.mail_address = mail_address
        self.timeout = timeout
        self._client: Optional[smtplib.SMTP] = None

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
