###############################################################################
# STAGE 1 - build-image
###############################################################################
FROM quay.io/redhat-services-prod/app-sre-tenant/container-images-master/qontract-reconcile-builder-master:1.2.0-1@sha256:bb4638c66aaaadd82b3f0b6e36f5551536ef34bc5cb881616d19dd5f36fc5d27 AS build-image
COPY --from=ghcr.io/astral-sh/uv:0.8.22@sha256:9874eb7afe5ca16c363fe80b294fe700e460df29a55532bbfea234a0f12eddb1 /uv /bin/uv

WORKDIR /work

COPY pyproject.toml uv.lock README.md ./
COPY helm helm
COPY tools tools
COPY reconcile reconcile

ENV \
    # use venv from ubi image
    UV_PROJECT_ENVIRONMENT=$APP_ROOT \
    # compile bytecode for faster startup
    UV_COMPILE_BYTECODE="true" \
    # disable uv cache. it doesn't make sense in a container
    UV_NO_CACHE=true

# Install dependencies and qontract-reconcile
RUN UV_DYNAMIC_VERSIONING_BYPASS="0.0.0" uv sync --frozen --no-group dev


###############################################################################
# STAGE 2 - dev-image
###############################################################################
FROM quay.io/redhat-services-prod/app-sre-tenant/container-images-master/qontract-reconcile-base-master:1.2.0-1@sha256:acce400b64894aa8afe7a269f6d991217edb168008f9a7b0533f71c3ba556711 AS dev-image
COPY --from=ghcr.io/astral-sh/uv:0.8.22@sha256:9874eb7afe5ca16c363fe80b294fe700e460df29a55532bbfea234a0f12eddb1 /uv /bin/uv

ENV \
    # use venv from ubi image
    UV_PROJECT_ENVIRONMENT=$APP_ROOT \
    # compile bytecode for faster startup
    UV_COMPILE_BYTECODE="true" \
    # disable uv cache. it doesn't make sense in a container
    UV_NO_CACHE=true

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
ENTRYPOINT ["/work/dev/run.sh"]


###############################################################################
# STAGE 3 - prod-image-pre-test
###############################################################################
FROM quay.io/redhat-services-prod/app-sre-tenant/container-images-master/qontract-reconcile-base-master:1.2.0-1@sha256:acce400b64894aa8afe7a269f6d991217edb168008f9a7b0533f71c3ba556711 AS prod-image-pre-test

# Tini
ENV TINI_VERSION=v0.19.0
ADD https://github.com/krallin/tini/releases/download/${TINI_VERSION}/tini /tini
RUN chmod +x /tini

# Keep the image up to date
RUN microdnf upgrade -y && microdnf clean all


WORKDIR /work
# the integration-manager needs the helm charts
RUN ln -s /work/helm /helm
# python environment
COPY --from=build-image $APP_ROOT $APP_ROOT
# qontract-reconcile code
COPY --from=build-image /work ./

ENTRYPOINT ["/tini", "--"]
CMD ["run-integration"]

###############################################################################
# STAGE 4 - unittest image
###############################################################################
FROM prod-image-pre-test AS test-image
COPY --from=ghcr.io/astral-sh/uv:0.8.22@sha256:9874eb7afe5ca16c363fe80b294fe700e460df29a55532bbfea234a0f12eddb1 /uv /bin/uv

ENV \
    # use venv from ubi image
    UV_PROJECT_ENVIRONMENT=$APP_ROOT \
    # disable uv cache. it doesn't make sense in a container
    UV_NO_CACHE=true

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
COPY --chown=0:0 --from=quay.io/redhat-services-prod/app-sre-tenant/container-images-master/qontract-reconcile-oc-master:1.0.1-1@sha256:41643b95b5fd875a096ed7123f68e9f82d10d7ad4a6728ef79e21abcadec199b \
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
