import time
import itertools

from functools import wraps


# source: https://www.calazan.com/retry-decorator-for-python-3/
def retry(exceptions=Exception, max_attempts=3):

    def deco_retry(f):

        @wraps(f)
        def f_retry(*args, **kwargs):
            for attempt in itertools.count(1):
                try:
                    return f(*args, **kwargs)
                except exceptions as e:
                    if attempt > max_attempts - 1:
                        raise e
                    time.sleep(attempt)
        return f_retry
    return deco_retry
