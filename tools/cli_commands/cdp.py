"""Continuous Deployment Promoter"""

import hashlib
from collections import namedtuple

from ruamel.yaml import YAML
from ruamel.yaml.compat import StringIO

RTTarget = namedtuple("RTTarget", ["resource_template", "target"])


def cdp_hash(saasfile: str, ref: str, target: list[str]) -> str:
    return hashlib.sha256(f"{saasfile}-{ref}-{target}".encode("utf-8")).hexdigest()[:6]


def to_rttarget(t: str) -> RTTarget:
    chunks = iter(t.split(",", 1))
    return RTTarget(next(chunks), next(chunks, None))


def cdp_bump_saasfile(content: str, ref: str, targets_str: list[str]) -> str:
    yml = YAML(typ="rt", pure=True)
    yml.preserve_quotes = True
    # Lets prevent line wraps
    yml.width = 4096

    targets = [to_rttarget(t) for t in targets_str]

    saas = yml.load(content)

    # counter = 0
    for rt in saas.get("resourceTemplates", []):
        rt_name = rt.get("name")

        if not rt_name:
            continue

        for target in rt.get("targets", []):
            target_name = target.get("name", None)
            if (rt_name, target_name) in targets:
                target["ref"] = ref
                # counter += 1

    # TODO:
    # if counter == 0:
    #    raise Exception for no changes

    new_content = "---\n"
    with StringIO() as stream:
        yml.dump(saas, stream)
        new_content += stream.getvalue() or ""

    return new_content
