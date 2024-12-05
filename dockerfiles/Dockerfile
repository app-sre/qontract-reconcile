###############################################################################
# STAGE 1 - build-image
###############################################################################
FROM quay.io/app-sre/qontract-reconcile-builder:0.7.0 AS build-image
COPY --from=ghcr.io/astral-sh/uv:0.5.6@sha256:92aa10fc236a5cbd3624c9909f855a860bd209fef17756c831ee84c478423517 /uv /bin/uv

WORKDIR /work

COPY pyproject.toml uv.lock README.md ./
COPY tools tools
COPY reconcile reconcile

ENV \
    # compile bytecode for faster startup
    UV_COMPILE_BYTECODE="true" \
    # disable uv cache. it doesn't make sense in a container
    UV_NO_CACHE=true

# Test lock file is up to date
# RUN --mount=source=.git,target=.git,type=bind uv lock --locked
# Install dependencies and qontract-reconcile
RUN --mount=source=.git,target=.git,type=bind uv sync --frozen --no-group dev --python /usr/bin/python3


###############################################################################
# STAGE 2 - dev-image
###############################################################################
FROM quay.io/app-sre/qontract-reconcile-base:0.14.0 AS dev-image
COPY --from=ghcr.io/astral-sh/uv:0.5.6@sha256:92aa10fc236a5cbd3624c9909f855a860bd209fef17756c831ee84c478423517 /uv /bin/uv

ARG CONTAINER_UID=1000
RUN useradd --uid ${CONTAINER_UID} reconcile && \
    chown -R reconcile /.terraform.d

WORKDIR /work

COPY --from=build-image --chown=reconcile:root /work/ ./
RUN --mount=source=.git,target=.git,type=bind uv sync --frozen --no-cache --group debugger --no-group dev
# Move .venv out of the workdir so it can't be overwritten by volume mount
RUN mv .venv /venv

USER reconcile
VOLUME ["/work"]
# Set the PATH to include the virtualenv
ENV PATH="/venv/bin:${PATH}"
ENTRYPOINT ["/work/dev/run.sh"]


###############################################################################
# STAGE 3 - prod-image
###############################################################################
FROM quay.io/app-sre/qontract-reconcile-base:0.14.0 AS prod-image

ARG quay_expiration=never
LABEL quay.expires-after=${quay_expiration}

# Tini
ENV TINI_VERSION v0.19.0
ADD https://github.com/krallin/tini/releases/download/${TINI_VERSION}/tini /tini
RUN chmod +x /tini

# Keep the image up to date
RUN microdnf upgrade -y && microdnf clean all

# Copy prod deployment related files
COPY dockerfiles/hack/run-integration.py /
COPY helm /helm

WORKDIR /work
COPY --from=build-image /work ./

# Set the PATH to include the virtualenv
ENV PATH="/work/.venv/bin:${PATH}"

ENTRYPOINT ["/tini", "--"]
CMD [ "/run-integration.py" ]


###############################################################################
# STAGE 4 - fips-prod-image
###############################################################################
FROM prod-image AS fips-prod-image
ENV OC_VERSION=4.10.15

# oc versions sometimes have issues with FIPS enabled systems requiring us to use specific
# versions in these environments so in this case we extract an older version of oc and kubectl
COPY --chown=0:0 --from=quay.io/app-sre/qontract-reconcile-oc:0.1.0 \
    /work/${OC_VERSION}/ /usr/local/bin/
