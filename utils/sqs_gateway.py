import os

class SQSGateway(object):
    """Wrapper around SQS AWS SDK"""

    def __init__(self):
        access_key = os.environ['aws_access_key_id']
        secret_key = os.environ['aws_secret_access_key']
        region_name = os.environ['region']
        session = boto3.Session(
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region_name,
        )
        self.sessions[account] = session
