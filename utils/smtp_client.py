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
    smtp_secret_path = config['smtp']['secret_path']
    smtp_config = config_from_vault(smtp_secret_path)
    host = smtp_config['server']
    port = smtp_config['port']
    _username = smtp_config['username']
    password = smtp_config['password']
    _mail_address = config['smtp']['mail_address']

    return init(host, port, _username, password)


def config_from_vault(vault_path):
    config = {}

    required_keys = ('password', 'port', 'require_tls', 'server', 'username')

    try:
        data = vault_client.read_all(vault_path)
    except vault_client.SecretNotFound as e:
        raise Exception("Could not retrieve SMTP config from vault: {}"
                        .format(e))

    try:
        for k in required_keys:
            config[k] = data[k]
    except KeyError as e:
        raise Exception("Missing expected SMTP config key in vault secret: {}"
                        .format(e))

    return config


def send_mail(name, subject, body):
    global _client
    global _username
    global _mail_address

    if _client is None:
        init_from_config()

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
