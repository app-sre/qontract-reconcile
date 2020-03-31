import os
import json
import tempfile
from utils.defer import defer
from subprocess import run, PIPE


class JsonnetError(Exception):
    def __init__(self, message):
        self.message = message

    def __str__(self):
        return(self.message)


def generate_object(jsonnet_string):
    try:
        fd, path = tempfile.mkstemp()
        defer(lambda: cleanup(path))
        os.write(fd, jsonnet_string.encode())
        os.close(fd)
    except Exception as e:
        raise JsonnetError("Error building jsonnet file: %s" % e)

    try:
        jsonnet_bundler_dir = os.environ['JSONNET_BUNDLER_DIR']
    except KeyError as e:
        raise JsonnetError("JSONNET_BUNDLER_DIR not set")

    cmd = ['jsonnet', '-J', jsonnet_bundler_dir, path]
    status = run(cmd, stdout=PIPE, stderr=PIPE)

    if status.returncode != 0:
        message = 'Error building json doc'
        if status.stderr:
            message += ": " + status.stderr.decode()

        raise JsonnetError(message)

    return json.loads(status.stdout)


def cleanup(path):
    try:
        os.unlink(path)
    except Exception:
        pass
