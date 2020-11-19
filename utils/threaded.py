import traceback
import functools
from multiprocessing.dummy import Pool as ThreadPool


def full_traceback(func):
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
    func_partial = functools.partial(full_traceback(func), **kwargs)
    try:
        return pool.map(func_partial, iterable)
    finally:
        pool.close()
        pool.join()


def estimate_available_thread_pool_size(thread_pool_size, targets_len):
    # if there are 20 threads and only 3 targets,
    # each thread can use ~20/3 threads internally.
    # if there are 20 threads and 100 targts,
    # each thread can use 1 thread internally.
    available_thread_pool_size = int(thread_pool_size / targets_len)
    return max(available_thread_pool_size, 1)
