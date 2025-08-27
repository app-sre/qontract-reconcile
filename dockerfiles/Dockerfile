###############################################################################
# STAGE 1 - build-image
###############################################################################
FROM quay.io/redhat-services-prod/app-sre-tenant/container-images-master/qontract-reconcile-builder-master:1.1.0-1@sha256:d557553fd542eefc2dbb1e524da0f068bf03d3fda885884587aa50a4006b9dee AS build-image
COPY --from=ghcr.io/astral-sh/uv:0.7.21@sha256:a64333b61f96312df88eafce95121b017cbff72033ab2dbc6398edb4f24a75dd /uv /bin/uv

WORKDIR /work

COPY pyproject.toml uv.lock README.md ./
COPY helm helm
COPY tools tools
COPY reconcile reconcile

ENV \
    # compile bytecode for faster startup
    UV_COMPILE_BYTECODE="true" \
    # disable uv cache. it doesn't make sense in a container
    UV_NO_CACHE=true

# Install dependencies and qontract-reconcile
RUN UV_DYNAMIC_VERSIONING_BYPASS="0.0.0" uv sync --frozen --no-group dev --python /usr/bin/python3


###############################################################################
# STAGE 2 - dev-image
###############################################################################
FROM quay.io/redhat-services-prod/app-sre-tenant/container-images-master/qontract-reconcile-base-master:1.1.0-1@sha256:095e6d5b029b561dd6f3d4394c691852bb96cc8587ebbc5092463b8d101893b8 AS dev-image
COPY --from=ghcr.io/astral-sh/uv:0.7.21@sha256:a64333b61f96312df88eafce95121b017cbff72033ab2dbc6398edb4f24a75dd /uv /bin/uv

ARG CONTAINER_UID=1000
RUN useradd --uid ${CONTAINER_UID} reconcile && \
    chown -R reconcile /.terraform.d

# Use a different workdir so venv can't be overwritten by volume mount
WORKDIR /opt/app-root/src

COPY --from=build-image --chown=reconcile:root /work/ ./
RUN UV_DYNAMIC_VERSIONING_BYPASS="0.0.0" uv sync --frozen --no-cache --group debugger --no-group dev

WORKDIR /work
USER reconcile
VOLUME ["/work", "/config"]
# Set the PATH to include the virtualenv
ENV PATH="/opt/app-root/src/.venv/bin:${PATH}"
ENTRYPOINT ["/work/dev/run.sh"]


###############################################################################
# STAGE 3 - prod-image-pre-test
###############################################################################
FROM quay.io/redhat-services-prod/app-sre-tenant/container-images-master/qontract-reconcile-base-master:1.1.0-1@sha256:095e6d5b029b561dd6f3d4394c691852bb96cc8587ebbc5092463b8d101893b8 AS prod-image-pre-test

# Tini
ENV TINI_VERSION=v0.19.0
ADD https://github.com/krallin/tini/releases/download/${TINI_VERSION}/tini /tini
RUN chmod +x /tini

# Keep the image up to date
RUN microdnf upgrade -y && microdnf clean all


WORKDIR /work
# the integration-manager needs the helm charts
RUN ln -s /work/helm /helm
COPY --from=build-image /work ./

# Set the PATH to include the virtualenv
ENV PATH="/work/.venv/bin:${PATH}"

ENTRYPOINT ["/tini", "--"]
CMD ["run-integration"]

###############################################################################
# STAGE 4 - unittest image
###############################################################################
FROM prod-image-pre-test AS test-image
COPY --from=ghcr.io/astral-sh/uv:0.7.21@sha256:a64333b61f96312df88eafce95121b017cbff72033ab2dbc6398edb4f24a75dd /uv /bin/uv

RUN microdnf install -y make

# Tests need the .git directory to run and infer version
COPY .git .git

# Install test dependencies
RUN uv sync --frozen --no-cache --group dev

# Run tests
COPY Makefile .
RUN make all-tests
RUN echo "true" > /is_tested

###############################################################################
# STAGE 5 - tested prod image
###############################################################################
FROM prod-image-pre-test AS prod-image

# Lets make sure we run tests when targeting prod-image
# However, we dont want any installed deps from test image
COPY --from=test-image /is_tested /is_tested

###############################################################################
# STAGE 6 - tested fips-prod-image
###############################################################################
FROM prod-image-pre-test AS fips-prod-image
ENV OC_VERSION=4.16.2

# oc versions sometimes have issues with FIPS enabled systems requiring us to use specific
# versions in these environments so in this case we extract an older version of oc and kubectl
COPY --chown=0:0 --from=quay.io/redhat-user-workloads/app-sre-tenant/container-images-master/qontract-reconcile-oc-master:1.0.0@sha256:46898dd2185948c155bd8cf16bdc009fd7acf90ac9b8a253cf3d390f041c7b1b \
    /work/${OC_VERSION}/ /usr/local/bin/

# Lets make sure we run tests when targeting fips-prod-image
# However, we dont want any installed deps from test image
COPY --from=test-image /is_tested /is_tested

###############################################################################
# STAGE 7 - PyPI publish package
###############################################################################
FROM test-image AS pypi

# Lets make sure we ran previous prod stage before uploading to pypi
COPY --from=prod-image /is_tested /is_tested
RUN echo "true" > /is_pypi_pushed

# qontract-reconcile version depends on git tags!
# The .git dir should already be part of the test image
RUN --mount=type=secret,id=app-sre-pypi-credentials/token export UV_PUBLISH_TOKEN=$(cat /run/secrets/app-sre-pypi-credentials/token); make pypi-konflux

###############################################################################
# STAGE 8 - tested and pypi pushed prod image
###############################################################################
FROM prod-image AS prod-image-post-pypi-push

# Lets make sure we pypi push
COPY --from=pypi /is_pypi_pushed /is_pypi_pushed
