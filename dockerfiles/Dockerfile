FROM quay.io/app-sre/qontract-reconcile-base:0.5.1 AS build-image

WORKDIR /work

COPY e2e_tests e2e_tests
COPY reconcile reconcile
COPY tools tools
COPY setup.py .

RUN curl -L -o /work/devel:kubic:libcontainers:stable.repo \
    https://download.opensuse.org/repositories/devel:/kubic:/libcontainers:/stable/CentOS_8/devel:kubic:libcontainers:stable.repo

RUN python3 -m pip install --upgrade pip setuptools wheel && \
    python3 -m pip wheel . --wheel-dir /work/wheels

FROM registry.access.redhat.com/ubi8/ubi-minimal:8.4

ENV TF_PLUGIN_LOCAL_DIR=/usr/local/share/terraform/
ENV TF_PLUGIN_CACHE_DIR=/.terraform.d/plugin-cache/

# COPY Terraform providers
COPY --from=build-image ${TF_PLUGIN_LOCAL_DIR} ${TF_PLUGIN_LOCAL_DIR}

# Tooling binaries
COPY --chown=0:0 --from=build-image \
    /usr/local/bin/kubectl \
    /usr/local/bin/oc \
    /usr/local/bin/terraform \
    /usr/local/bin/git-secrets \
    /usr/local/bin/promtool \
    /usr/local/bin/amtool \
    /usr/local/bin/

# App Wheel files
COPY --from=build-image /work /tmp/work

RUN cp /tmp/work/devel:kubic:libcontainers:stable.repo /etc/yum.repos.d/ && \
    microdnf install \
        git \
        glibc-langpack-en \
        openssh-clients \
        openssl \
        python3.9 \
        skopeo && \
    microdnf clean all

RUN python3.9 -m pip install --upgrade pip setuptools wheel && \
    python3.9 -m pip install --no-index --find-links=/tmp/work/wheels qontract-reconcile && \
    rm -rf /tmp/work && \
    mkdir -p ${TF_PLUGIN_CACHE_DIR}

COPY dockerfiles/hack/run-integration.py /run-integration.py
CMD [ "/run-integration.py" ]
