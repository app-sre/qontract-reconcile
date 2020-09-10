import smtplib
import imaplib

import utils.secret_reader as secret_reader

from utils.config import get_config

from sretoolbox.utils import retry
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.header import Header
from email.utils import formataddr

_client = None
_server = None
_username = None
_mail_address = None


def init(host, port, username, password, client_only):
    global _client
    global _server

    if _client is None:
        s = smtplib.SMTP(
            host=host,
            port=str(port)
        )
        s.send
        s.starttls()
        s.login(username, password)
        _client = s
    if _server is None and not client_only:
        s = imaplib.IMAP4_SSL(
            host=host
        )
        s.login(username, password)
        _server = s

    return _client, _server


def teardown():
    global _client

    _client.quit()


def init_from_config(settings, client_only=True):
    global _username
    global _mail_address

    config = get_config()
    smtp_secret_path = config['smtp']['secret_path']
    smtp_config = get_smtp_config(smtp_secret_path, settings)
    host = smtp_config['server']
    port = smtp_config['port']
    _username = smtp_config['username']
    password = smtp_config['password']
    _mail_address = config['smtp']['mail_address']

    return init(host, port, _username, password, client_only=client_only)


def get_smtp_config(path, settings):
    config = {}

    required_keys = ('password', 'port', 'require_tls', 'server', 'username')
    data = secret_reader.read_all({'path': path}, settings=settings)

    try:
        for k in required_keys:
            config[k] = data[k]
    except KeyError as e:
        raise Exception("Missing expected SMTP config key in vault secret: {}"
                        .format(e))

    return config


def get_mails(folder='INBOX', criteria='ALL', settings=None):
    global _server

    if _server is None:
        init_from_config(settings, client_only=False)

    _server.select(f'"{folder}"')

    result, data = _server.uid('search', None, criteria)
    uids = [s for s in data[0].split()]
    results = []
    for uid in uids:
        result, data = _server.uid('fetch', uid, '(RFC822)')
        msg = data[0][1].decode('utf-8')
        results.append({'uid': uid, 'msg': msg})

    return results


@retry()
def send_mail(names, subject, body, settings=None):
    global _client
    global _username
    global _mail_address

    if _client is None:
        init_from_config(settings)

    msg = MIMEMultipart()
    from_name = str(Header('App SRE team automation', 'utf-8'))
    msg['From'] = formataddr((from_name, _username))
    to = set()
    for name in names:
        if '@' in name:
            to.add(name)
        else:
            to.add(f"{name}@{_mail_address}")
    msg['To'] = ', '.join(to)
    msg['Subject'] = subject

    # add in the message body
    msg.attach(MIMEText(body, 'plain'))

    # send the message via the server set up earlier.
    _client.sendmail(_username, to, msg.as_string())


def send_mails(mails, settings=None):
    global _client

    init_from_config(settings)
    try:
        for name, subject, body in mails:
            send_mail([name], subject, body)
    finally:
        teardown()


def get_recepient(org_username, settings):
    global _client
    global _mail_address

    if _client is None:
        init_from_config(settings)

    return f"{org_username}@{_mail_address}"
