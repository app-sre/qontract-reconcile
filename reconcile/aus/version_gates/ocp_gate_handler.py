from reconcile.aus.version_gates.handler import NoopGateHandler

GATE_LABEL = "api.openshift.com/gate-ocp"


class OCPGateHandler(NoopGateHandler):
    """
    Right now we just ack all gate-ocp gates...
    We could do better in the future, e.g. inspecting insights findings on the cluster
    """

    pass
