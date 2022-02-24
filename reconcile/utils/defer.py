from functools import wraps


# source: https://towerbabbel.com/go-defer-in-python/
def defer(func):
    """Defer code execution until the surrounding function returns.
    Useful for registering cleanup work.
    """

    @wraps(func)
    def func_wrapper(*args, **kwargs):
        deferred = []

        def defer(f):
            return deferred.append(f)

        try:
            return func(*args, defer=defer, **kwargs)
        finally:
            deferred.reverse()
            for f in deferred:
                f()

    return func_wrapper
