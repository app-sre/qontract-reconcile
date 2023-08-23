import json
import tempfile
from collections.abc import Mapping
from pathlib import Path
from subprocess import (
    CalledProcessError,
    run,
)
from typing import Any

import yaml

from reconcile.utils.runtime.sharding import ShardSpec


class HelmTemplateError(Exception):
    pass


class JSONEncoder(json.JSONEncoder):
    def default(self, o: Any) -> Any:
        if isinstance(o, ShardSpec):
            return o.__dict__
        return super().default(o)


def template(values: Mapping[str, Any]) -> Mapping[str, Any]:
    try:
        with tempfile.NamedTemporaryFile(mode="w+") as values_file:
            values_file.write(json.dumps(values, cls=JSONEncoder))
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
            cwd = Path(__file__).parent.parent.parent
            result = run(cmd, capture_output=True, check=True, cwd=cwd)
    except CalledProcessError as e:
        msg = f'Error running helm template [{" ".join(cmd)}]'
        if e.stdout:
            msg += f" {e.stdout.decode()}"
        if e.stderr:
            msg += f" {e.stderr.decode()}"
        raise HelmTemplateError(msg)

    return yaml.safe_load(result.stdout.decode())
