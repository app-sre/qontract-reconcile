import tempfile
import json
import yaml

from typing import Any, Mapping
from subprocess import run, PIPE, CalledProcessError


class HelmTemplateError(Exception):
    pass


def template(values: Mapping[str, Any]) -> Mapping[str, Any]:
    try:
        with tempfile.NamedTemporaryFile(mode="w+") as values_file:
            values_file.write(json.dumps(values))
            values_file.flush()
            cmd = [
                "helm",
                "template",
                "./helm/qontract-reconcile",
                "-n",
                "qontract-reconcile",
                "-f",
                values_file.name,
            ]
            result = run(cmd, stdout=PIPE, stderr=PIPE, check=True)
    except CalledProcessError as e:
        msg = f'Error running helm template [{" ".join(cmd)}]'
        if e.stdout:
            msg += f" {e.stdout.decode()}"
        if e.stderr:
            msg += f" {e.stderr.decode()}"
        raise HelmTemplateError(msg)

    return yaml.safe_load(result.stdout.decode())
