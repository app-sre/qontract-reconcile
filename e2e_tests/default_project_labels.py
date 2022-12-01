import logging
import re

from sretoolbox.utils import threaded

import e2e_tests.test_base as tb
from reconcile.utils.defer import defer

QONTRACT_E2E_TEST = "default-project-labels"


def test_cluster(cluster, oc_map, pattern):
    oc = oc_map.get(cluster)
    if not oc:
        logging.log(level=oc.log_level, msg=oc.message)
        return None
    logging.info("[{}] validating default Project labels".format(cluster))

    projects = [
        p
        for p in oc.get_all("Project")["items"]
        if p["status"]["phase"] != "Terminating"
        and not re.search(pattern, p["metadata"]["name"])
        and "api.openshift.com/id" not in p["metadata"].get("labels", {})
    ]

    for project in projects:
        logging.info(
            "[{}/{}] validating default Project labels".format(
                cluster, project["metadata"]["name"]
            )
        )
        try:
            assert project["metadata"]["labels"]["name"] == project["metadata"]["name"]
            monitoring_label = "openshift.io/workload-monitoring"
            assert project["metadata"]["labels"][monitoring_label] == "true"
        except Exception:
            logging.error(f"[{cluster}] failed test {QONTRACT_E2E_TEST}")


@defer
def run(thread_pool_size=10, defer=None):
    oc_map = tb.get_oc_map(QONTRACT_E2E_TEST)
    defer(oc_map.cleanup)
    pattern = tb.get_namespaces_pattern()
    threaded.run(
        test_cluster,
        oc_map.clusters(),
        thread_pool_size,
        oc_map=oc_map,
        pattern=pattern,
    )
