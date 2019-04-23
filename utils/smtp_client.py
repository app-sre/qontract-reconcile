import smtplib

import utils.vault_client as vault_client

from utils.config import get_config

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.header import Header
from email.utils import formataddr

_client = None
_username = None
_mail_address = None


def init(host, port, username, password):
    global _client

    if _client is None:
        s = smtplib.SMTP(
            host=host,
            port=str(port)
        )
        s.send
        s.starttls()
        s.login(username, password)
        _client = s

    return _client


def teardown():
    global _client

    _client.quit()


def init_from_config():
    global _username
    global _mail_address

    config = get_config()

    config = get_config()
    smtp_secret_path = config['smtp']['secret_path']
    smtp_config = vault_client.read_all(smtp_secret_path)
    host = smtp_config['server']
    port = smtp_config['port']
    _username = smtp_config['username']
    password = smtp_config['password']
    _mail_address = config['smtp']['mail_address']

    return init(host, port, _username, password)


def send_mail(name, subject, body):
    global _client
    global _username
    global _mail_address

    msg = MIMEMultipart()
    from_name = str(Header('App SRE team automation', 'utf-8'))
    to = '{}@{}'.format(name, _mail_address)
    msg['From'] = formataddr((from_name, _username))
    msg['To'] = to
    msg['Subject'] = subject

    # add in the message body
    msg.attach(MIMEText(body, 'plain'))

    # send the message via the server set up earlier.
    _client.sendmail(_username, to, msg.as_string())


def send_mails(mails):
    global _client

    init_from_config()
    try:
        for name, subject, body in mails:
            send_mail(name, subject, body)
    finally:
        teardown()
