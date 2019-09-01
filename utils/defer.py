from functools import wraps


# source: https://towerbabbel.com/go-defer-in-python/
def defer(func):
  @wraps(func)
  def func_wrapper(*args, **kwargs):
    deferred = []
    defer = lambda f: deferred.append(f)
    try:
      return func(*args, defer=defer, **kwargs)
    finally:
      deferred.reverse()
      for f in deferred:
        f()
  return func_wrapper
