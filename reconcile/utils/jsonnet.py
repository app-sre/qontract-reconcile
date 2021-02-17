import json
import os
import subprocess
import tempfile

from reconcile.utils.defer import defer


class JsonnetError(Exception):
    pass


def generate_object(jsonnet_string):
    try:
        fd, path = tempfile.mkstemp()
        defer(lambda: cleanup(path))
        os.write(fd, jsonnet_string.encode())
        os.close(fd)
    except Exception as e:
        raise JsonnetError(f'Error building jsonnet file: {e}')

    try:
        jsonnet_bundler_dir = os.environ['JSONNET_VENDOR_DIR']
    except KeyError as e:
        raise JsonnetError('JSONNET_VENDOR_DIR not set')

    cmd = ['jsonnet', '-J', jsonnet_bundler_dir, path]
    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, check=True)
    except subprocess.CalledProcessError as e:
        raise JsonnetError(f'Error building json doc: {e}')

    return json.loads(result.stdout)


def cleanup(path):
    try:
        os.unlink(path)
    except Exception:
        pass
