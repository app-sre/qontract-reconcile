import smtplib
import imaplib

from reconcile.utils.secret_reader import SecretReader

from reconcile.utils.config import get_config

from sretoolbox.utils import retry
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.header import Header
from email.utils import formataddr


class SmtpClient:
    def __init__(self, settings):
        config = get_config()

        smtp_secret_path = config['smtp']['secret_path']
        smtp_config = self.get_smtp_config(smtp_secret_path, settings)
        self.host = smtp_config['server']
        self.port = str(smtp_config['port'])
        self.user = smtp_config['username']
        self.passwd = smtp_config['password']
        self.mail_address = config['smtp']['mail_address']

        self.client = smtplib.SMTP(host=self.host,
                                   port=self.port)
        self.client.send
        self.client.starttls()
        self.client.login(self.user, self.passwd)

        self._server = None

    @property
    def server(self):
        if self._server is None:
            self._server = imaplib.IMAP4_SSL(host=self.host)
            self._server.login(self.user, self.passwd)
        return self._server

    @staticmethod
    def get_smtp_config(path, settings):
        config = {}
        required_keys = ('password', 'port', 'require_tls', 'server',
                         'username')
        secret_reader = SecretReader(settings=settings)
        data = secret_reader.read_all({'path': path})
        try:
            for k in required_keys:
                config[k] = data[k]
        except KeyError as e:
            raise Exception(f'Missing expected SMTP config '
                            f'key in vault secret: {e}')
        return config

    def get_mails(self, folder='INBOX', criteria='ALL'):
        self.server.select(f'"{folder}"')
        result, data = self.server.uid('search', None, criteria)
        uids = [s for s in data[0].split()]
        results = []
        for uid in uids:
            result, data = self.server.uid('fetch', uid, '(RFC822)')
            msg = data[0][1].decode('utf-8')
            results.append({'uid': uid, 'msg': msg})
        return results

    def send_mails(self, mails):
        for name, subject, body in mails:
            self.send_mail([name], subject, body)

    @retry()
    def send_mail(self, names, subject, body):
        msg = MIMEMultipart()
        from_name = str(Header('App SRE team automation', 'utf-8'))
        msg['From'] = formataddr((from_name, self.user))
        to = set()
        for name in names:
            if '@' in name:
                to.add(name)
            else:
                to.add(f"{name}@{self.mail_address}")
        msg['To'] = ', '.join(to)
        msg['Subject'] = subject
        # add in the message body
        msg.attach(MIMEText(body, 'plain'))
        self.client.sendmail(self.user, to, msg.as_string())

    def get_recipient(self, org_username):
        return f'{org_username}@{self.mail_address}'
