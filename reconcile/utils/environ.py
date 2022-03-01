import os

from functools import wraps


def environ(variables=None):
    """Check that environment variables are set before execution."""
    if variables is None:
        variables = []

    def deco_environ(f):
        @wraps(f)
        def f_environ(*args, **kwargs):
            for e in variables:
                if e not in os.environ or os.environ[e] == "":
                    raise KeyError("Could not find environment variable: {}".format(e))
            f(*args, **kwargs)

        return f_environ

    return deco_environ
