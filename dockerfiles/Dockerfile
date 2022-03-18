FROM quay.io/app-sre/qontract-reconcile-builder:0.2.0 as build-image

WORKDIR /work

COPY e2e_tests e2e_tests
COPY reconcile reconcile
COPY tools tools
COPY setup.py .
COPY dockerfiles/hack/run-integration.py .

RUN python3 -m pip install --no-cache-dir --upgrade pip setuptools wheel && \
    python3 -m pip wheel . --wheel-dir /work/wheels


FROM quay.io/app-sre/qontract-reconcile-base:0.7.2 as dev-image

ARG CONTAINER_UID=1000
RUN useradd --uid ${CONTAINER_UID} reconcile

RUN python3 -m pip install --no-cache-dir --upgrade pip setuptools wheel

# Cache mount. We don't need te wheel files in the final image.
# This COPY will create a layer with all the wheel files to install the app.
# This layer is not needed in the final image, so we can leverage a cache mount
# to get rid of it. Implement the cache mount un the RUN command when we are able to
# to use the buildkit features.
COPY --from=build-image /work/ /tmp/work/
#RUN --mount=type=cache,target=/tmp/work/,from=build-image,source=/work \

COPY . /work
WORKDIR /work

RUN python3 -m pip install --no-cache-dir --no-index --find-links=/tmp/work/wheels qontract-reconcile
RUN python3 -m pip install -e .

RUN chown -R reconcile /work && \
    chown -R reconcile /.terraform.d

USER reconcile
VOLUME ["/work"]
CMD [ "/work/dev/run.sh" ]


FROM quay.io/app-sre/qontract-reconcile-base:0.7.2 as prod-image

# Cache mount. We don't need te wheel files in the final image.
# This COPY will create a layer with all the wheel files to install the app.
# This layer is not needed in the final image, so we can leverage a cache mount
# to get rid of it. Implement the cache mount un the RUN command when we are able to
# to use the buildkit features.
COPY --from=build-image /work/ /tmp/work/
#RUN --mount=type=cache,target=/tmp/work/,from=build-image,source=/work \

RUN microdnf upgrade -y && \
    python3 -m pip install --no-cache-dir --upgrade pip setuptools wheel && \
    python3 -m pip install --no-cache-dir --no-index --find-links=/tmp/work/wheels qontract-reconcile && \
    cp /tmp/work/run-integration.py /run-integration.py

CMD [ "/run-integration.py" ]
