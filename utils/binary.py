from functools import wraps
from distutils.spawn import find_executable


def binary(binaries=[]):
    """Check that a binary exists before execution."""
    def deco_binary(f):
        @wraps(f)
        def f_binary(*args, **kwargs):
            for b in binaries:
                if not find_executable(b):
                    raise Exception(
                        "Aborting: Could not find binary: {}".format(b))
            f(*args, **kwargs)
        return f_binary
    return deco_binary
