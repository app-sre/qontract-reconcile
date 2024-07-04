import json
import os
import tempfile
from collections.abc import Iterable, Mapping
from subprocess import (
    CalledProcessError,
    run,
)
from typing import Any

import yaml

from reconcile.utils import git
from reconcile.utils.runtime.sharding import ShardSpec


class HelmTemplateError(Exception):
    pass


class JSONEncoder(json.JSONEncoder):
    def default(self, o: Any) -> Any:
        if isinstance(o, ShardSpec):
            return o.__dict__
        return super().default(o)


def do_template(
    values: Mapping[str, Any],
    path: str,
    name: str,
) -> str:
    try:
        with open(os.path.join(path, "Chart.yaml"), encoding="locale") as chart_file:
            chart = yaml.safe_load(chart_file)
            if dependencies := chart.get("dependencies"):
                for dep in dependencies:
                    if repo := dep.get("repository"):
                        cmd = [
                            "helm",
                            "repo",
                            "add",
                            dep["name"],
                            repo,
                        ]
                        run(cmd, capture_output=False, check=True)
                cmd = [
                    "helm",
                    "dependency",
                    "build",
                    path,
                ]
                run(cmd, capture_output=False, check=True)
        with tempfile.NamedTemporaryFile(mode="w+", encoding="locale") as values_file:
            values_file.write(json.dumps(values, cls=JSONEncoder))
            values_file.flush()
            cmd = [
                "helm",
                "template",
                path,
                "-n",
                name,
                "-f",
                values_file.name,
            ]
            result = run(cmd, capture_output=True, check=True)
    except CalledProcessError as e:
        msg = f'Error running helm template [{" ".join(cmd)}]'
        if e.stdout:
            msg += f" {e.stdout.decode()}"
        if e.stderr:
            msg += f" {e.stderr.decode()}"
        raise HelmTemplateError(msg)

    return result.stdout.decode()


def template(
    values: Mapping[str, Any],
    path: str = "./helm/qontract-reconcile",
    name: str = "qontract-reconcile",
) -> Mapping[str, Any]:
    return yaml.safe_load(do_template(values=values, path=path, name=name))


def template_all(
    url: str,
    path: str,
    name: str,
    values: Mapping[str, Any],
    ssl_verify: bool = True,
) -> Iterable[Mapping[str, Any]]:
    with tempfile.TemporaryDirectory() as wd:
        git.clone(url, wd, depth=1, verify=ssl_verify)
        return yaml.safe_load_all(
            do_template(values=values, path=f"{wd}{path}", name=name)
        )
