
from functools import wraps
import time

class StatusCodeError(Exception):
    pass


class NoOutputError(Exception):
    pass

def retry():

    def deco_retry(f):

        @wraps(f)
        def f_retry(*args, **kwargs):
            attempt = 0
            attempts = 3
            while True:
                try:
                    return f(*args, **kwargs)
                except Exception as e:
                    attempt += 1
                    if attempt == attempts:
                        raise e
                    else:
                        time.sleep(attempt)
        return f_retry
    return deco_retry