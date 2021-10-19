FROM quay.io/app-sre/qontract-reconcile-builder:0.1.0 as build-image

WORKDIR /work

COPY e2e_tests \
     reconcile \
     tools \
     setup.py \
     dockerfiles/hack/run-integration.py \
     /work/

RUN python3 -m pip install --upgrade pip setuptools wheel && \
    python3 -m pip wheel . --wheel-dir /work/wheels


FROM quay.io/app-sre/qontract-reconcile-base:0.5.3

RUN --mount=type=cache,target=/tmp/work/,from=build-image,source=/work \
    microdnf upgrade -y && \
    python3 -m pip install --upgrade pip setuptools wheel && \
    python3 -m pip install --no-index --find-links=/tmp/work/wheels qontract-reconcile && \
    mv /tmp/work/run-integration.py /run-integration.py


CMD [ "/run-integration.py" ]
