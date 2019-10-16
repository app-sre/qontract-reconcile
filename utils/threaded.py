from multiprocessing.dummy import Pool as ThreadPool
from functools import partial

def full_traceback(func):
    import traceback, functools
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            msg = "{}\n\nOriginal {}".format(e, traceback.format_exc())
            raise type(e)(msg)
    return wrapper

def run(func, iterable, thread_pool_size, **kwargs):
    """run executes a function for each item in the input iterable.
    execution will be multithreaded according to the input thread_pool_size.
    kwargs are passed to the input function (optional)."""

    pool = ThreadPool(thread_pool_size)
    func_partial = partial(full_traceback(func), **kwargs)
    return pool.map(func_partial, iterable)
