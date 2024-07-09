###############################################################################
# STAGE 1 - build-image
###############################################################################
FROM quay.io/app-sre/qontract-reconcile-builder:0.6.0 as build-image

WORKDIR /work

COPY helm helm
COPY reconcile reconcile
COPY release release
COPY tools tools
COPY setup.py .
COPY GIT_VERSION .
COPY dockerfiles/hack/run-integration.py .

RUN python3 -m pip install --no-cache-dir --upgrade pip setuptools wheel && \
    python3 -m pip wheel . --wheel-dir /work/wheels


###############################################################################
# STAGE 2 - dev-image
###############################################################################
FROM quay.io/app-sre/qontract-reconcile-base:0.13.0 as dev-image

ARG CONTAINER_UID=1000
RUN useradd --uid ${CONTAINER_UID} reconcile

RUN python3 -m pip install --no-cache-dir --upgrade pip setuptools wheel

# Cache mount. We don't need te wheel files in the final image.
# This COPY will create a layer with all the wheel files to install the app.
# This layer is not needed in the final image, so we can leverage a cache mount
# to get rid of it. Implement the cache mount with the RUN command when we are
# able to use the buildkit features.
COPY --from=build-image /work/ /tmp/work/

COPY . /work
WORKDIR /work

RUN python3 -m pip install --no-cache-dir --no-index --find-links=/tmp/work/wheels qontract-reconcile
RUN python3 -m pip install -e .
RUN python3 -m pip install -r /work/requirements/requirements-debugger.txt

RUN chown -R reconcile /work && \
    chown -R reconcile /.terraform.d

USER reconcile
VOLUME ["/work"]
ENTRYPOINT ["/work/dev/run.sh"]

###############################################################################
# STAGE 3 - prod-image
###############################################################################
FROM quay.io/app-sre/qontract-reconcile-base:0.12.4 as prod-image

ARG quay_expiration=never
LABEL quay.expires-after=${quay_expiration}

# Tini
ENV TINI_VERSION v0.19.0
ADD https://github.com/krallin/tini/releases/download/${TINI_VERSION}/tini /tini
RUN chmod +x /tini

# Cache mount. We don't need te wheel files in the final image.
# This COPY will create a layer with all the wheel files to install the app.
# This layer is not needed in the final image, so we can leverage a cache mount
# to get rid of it. Implement the cache mount un the RUN command when we are able to
# to use the buildkit features.
COPY --from=build-image /work/ /tmp/work/

RUN microdnf upgrade -y && \
    python3 -m pip install --no-cache-dir --upgrade pip setuptools wheel && \
    python3 -m pip install --no-cache-dir --no-index --find-links=/tmp/work/wheels qontract-reconcile && \
    mkdir /helm && cp -r /tmp/work/helm/* /helm && \
    cp /tmp/work/run-integration.py /run-integration.py

ENTRYPOINT ["/tini", "--"]
CMD [ "/run-integration.py" ]

###############################################################################
# STAGE 4 - fips-prod-image
###############################################################################
FROM prod-image as fips-prod-image
ENV OC_VERSION=4.10.15

# oc versions sometimes have issues with FIPS enabled systems requiring us to use specific
# versions in these environments so in this case we extract an older version of oc and kubectl
COPY --chown=0:0 --from=quay.io/app-sre/qontract-reconcile-oc:0.1.0 \
    /work/${OC_VERSION}/ /usr/local/bin/
