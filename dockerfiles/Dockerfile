FROM quay.io/app-sre/qontract-base:6e1dd13 AS jsonnet-builder

ENV GOPATH=/go
ENV JSONNET_VERSION=v0.15.0
ENV JSONNET_BUNDLER_VERSION=v0.3.1
ENV VALET_LIBSONNET_VERSION=d2a774e73549a202f97982dd6982daccdde0035e

RUN mkdir /jsonnet && \
    git clone https://github.com/google/jsonnet.git --depth 1 /jsonnet && \
    cd /jsonnet && \
    git checkout -b ${JSONNET_VERSION} && \
    make

RUN dnf install -y go && \
    mkdir -p /go && \
    chmod -R 777 /go && \
    GO111MODULE=on go get github.com/jsonnet-bundler/jsonnet-bundler/cmd/jb@${JSONNET_BUNDLER_VERSION}

WORKDIR /jsonnet-bundler
RUN /go/bin/jb init && \
    /go/bin/jb install https://github.com/app-sre/valet-libsonnet@${VALET_LIBSONNET_VERSION}

FROM quay.io/app-sre/qontract-base:6e1dd13 AS terraform-providers-downloader

ENV VERSIONS="3.22.0"

RUN cd /tmp/; rm -rf /tmp/terraform-* ; rm -rf /tmp/package-* ;\
    for version in ${VERSIONS}; do \
    mkdir -p /tmp/terraform-providers/${version}/linux_amd64 ;\
    curl -o /tmp/package-${version}.zip https://releases.hashicorp.com/terraform-provider-aws/${version}/terraform-provider-aws_${version}_linux_amd64.zip; \
    unzip /tmp/package-${version}.zip -d /tmp/terraform-providers/${version}/linux_amd64/; \
    done

FROM quay.io/app-sre/qontract-base:6e1dd13

ENV OC_VERSION=4.6.1
ENV TF_VERSION=0.13.5
ENV GIT_SECRETS_VERSION=1.3.0
ENV JSONNET_VENDOR_DIR=/opt/jsonnet-bundler/vendor
ENV PROMETHEUS_VERSION=2.23.0

RUN curl https://mirror.openshift.com/pub/openshift-v4/clients/ocp/${OC_VERSION}/openshift-client-linux.tar.gz -o oc.tar.gz &&\
    tar -zvxf oc.tar.gz && \
    mv oc kubectl /usr/local/bin && \
    rm oc.tar.gz

RUN curl https://releases.hashicorp.com/terraform/${TF_VERSION}/terraform_${TF_VERSION}_linux_amd64.zip --output terraform.zip && \
    unzip terraform.zip && \
    mv terraform /usr/local/bin/terraform && \
    rm terraform.zip

RUN curl https://github.com/awslabs/git-secrets/archive/${GIT_SECRETS_VERSION}.tar.gz -L -o git-secrets.tar.gz && \
    tar -zvxf git-secrets.tar.gz git-secrets-${GIT_SECRETS_VERSION}/git-secrets && \
    mv git-secrets-${GIT_SECRETS_VERSION}/git-secrets /usr/local/bin/git-secrets && \
    rm -rf git-secrets*

RUN curl -sfL https://github.com/prometheus/prometheus/releases/download/v${PROMETHEUS_VERSION}/prometheus-${PROMETHEUS_VERSION}.linux-amd64.tar.gz | tar -zxf - -C /usr/local/bin --strip-components=1 prometheus-${PROMETHEUS_VERSION}.linux-amd64/promtool

COPY --from=jsonnet-builder /jsonnet/jsonnet /usr/local/bin/jsonnet
COPY --from=jsonnet-builder /jsonnet-bundler/vendor ${JSONNET_VENDOR_DIR}
RUN find ${JSONNET_VENDOR_DIR} -type d -exec chmod 0755 {} \;

RUN mkdir -p /.terraform.d/plugin-cache
COPY --from=terraform-providers-downloader /tmp/terraform-providers/ /.terraform.d/plugins/registry.terraform.io/hashicorp/aws/
RUN find /.terraform.d/ -type d -exec chmod 0755 {} \;
RUN chmod 0775 /.terraform.d/plugin-cache

WORKDIR /reconcile

COPY e2e_tests e2e_tests
COPY reconcile reconcile
COPY tools tools
COPY templates templates
COPY setup.py .

RUN python3 setup.py install

COPY dockerfiles/hack/run-integration.py /run-integration.py
CMD [ "/run-integration.py" ]
