import logging
import json
import subprocess
import tempfile
import shutil


class JsonnetBundler():
    """Wrapper around the Jsonnet Bundler utility"""

    def __init__(self, jsonnetfile):
        """Initialize a jsonnet directory with the provided jsonnetfile"""
        self.temp_dir_path = tempfile.mkdtemp()

        with open(self.temp_dir_path + "/jsonnetfile.json", 'w') as f:
            json.dump(json.loads(jsonnetfile), f)

        self.install()

    def get_dir_path(self):
        return self.temp_dir_path

    def install(self):
        """Initializes a jsonnet directory with the provided jsonnetfile"""
        cmd = ['jb', 'install']
        subprocess.call(cmd, cwd=self.temp_dir_path)

    def update(self):
        """
        Run jb update on the given directory
        """
        cmd = ['jb', 'update']
        subprocess.call(cmd, cwd=self.temp_dir_path)

    def cleanup(self):
        """Removes the temporary directory"""
        try:
            shutil.rmtree(self.temp_dir_path)
        except Exception:
            logging.debug("Unable to delete temporary jsonnet directory")
            pass
