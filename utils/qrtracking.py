import time

from functools import wraps

from reconcile.status import RunningState
from utils.metrics import reconcile_time


def elapsed_seconds_from_commit_metric(function):

    @wraps(function)
    def wrapper(*args, **kwargs):
        runing_state = RunningState()
        result = function(*args, **kwargs)

        commit_time = float(runing_state.timestamp)
        time_spent = time.time() - commit_time

        name = f'{function.__module__}.{function.__qualname__}'
        reconcile_time.labels(
            name=name,
            integration=runing_state.integration
        ).observe(amount=time_spent)

        return result

    return wrapper
