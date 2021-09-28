FROM quay.io/app-sre/qontract-reconcile-base:0.5.1

WORKDIR /work

COPY e2e_tests e2e_tests
COPY reconcile reconcile
COPY tools tools
COPY setup.py .

RUN dnf install -y python3 python3-pip python3-devel git make tar gzip unzip gcc gcc-c++ openssh-clients openssl glibc-langpack-en skopeo && \
    python3 -m pip install --upgrade pip setuptools wheel

RUN python3 -m pip wheel . --wheel-dir /work/wheels




FROM quay.io/app-sre/qontract-reconcile-base:0.4.0

RUN curl -L -o /etc/yum.repos.d/devel:kubic:libcontainers:stable.repo \
    https://download.opensuse.org/repositories/devel:/kubic:/libcontainers:/stable/CentOS_8/devel:kubic:libcontainers:stable.repo && \
    microdnf install \
        git \
        glibc-langpack-en \
        openssh-clients \
        openssl \
        python3 \
        python3-pip \
        skopeo && \
    microdnf clean all

COPY --from=build-image /work /tmp/work

RUN python3 -m pip install --upgrade pip setuptools wheel && \
    python3 -m pip install --no-index --find-links=/tmp/work/wheels qontract-reconcile && \
    rm -rf /tmp/work

COPY dockerfiles/hack/run-integration.py /run-integration.py
CMD [ "/run-integration.py" ]
