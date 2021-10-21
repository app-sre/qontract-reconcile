FROM quay.io/app-sre/qontract-reconcile-builder:0.1.0 as build-image

WORKDIR /work

COPY e2e_tests e2e_tests
COPY reconcile reconcile
COPY tools tools
COPY setup.py .

RUN python3 -m pip install --no-cache-dir --upgrade pip setuptools wheel && \
    python3 -m pip wheel . --wheel-dir /work/wheels


FROM quay.io/app-sre/qontract-reconcile-base:0.6.0

# Cache mount. We don't need te wheel files in the final image.
RUN --mount=type=cache,target=/tmp/work/,from=build-image,source=/work \
    microdnf upgrade -y && \
    python3 -m pip install --no-cache-dir --upgrade pip setuptools wheel && \
    python3 -m pip install --no-cache-dir --no-index --find-links=/tmp/work/wheels qontract-reconcile

COPY dockerfiles/hack/run-integration.py /run-integration.py

CMD [ "/run-integration.py" ]
