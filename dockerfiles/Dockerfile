FROM centos:7 AS jsonnet-builder

ENV GOPATH=/go
ENV JSONNET_VERSION=v0.15.0
ENV JSONNET_BUNDLER_VERSION=v0.3.1
ENV VALET_LIBSONNET_VERSION=d2a774e73549a202f97982dd6982daccdde0035e

RUN yum install -y epel-release git make gcc-c++

RUN mkdir /jsonnet && \
    git clone https://github.com/google/jsonnet.git --depth 1 /jsonnet && \
    cd /jsonnet && \
    git checkout -b ${JSONNET_VERSION} && \
    make

RUN yum install -y go && \
    mkdir -p /go && \
    chmod -R 777 /go && \
    GO111MODULE=on go get github.com/jsonnet-bundler/jsonnet-bundler/cmd/jb@${JSONNET_BUNDLER_VERSION}

WORKDIR /jsonnet-bundler
RUN /go/bin/jb init && \
    /go/bin/jb install https://github.com/app-sre/valet-libsonnet@${VALET_LIBSONNET_VERSION}

FROM centos:7

ENV LC_ALL=en_US.utf8
ENV LANG=en_US.utf8
ENV TF_VERSION=0.11.14
ENV GIT_SECRETS_VERSION=1.3.0
ENV JSONNET_VENDOR_DIR=/opt/jsonnet-bundler/vendor

RUN yum install -y centos-release-openshift-origin && \
    yum install -y http://opensource.wandisco.com/centos/7/git/x86_64/wandisco-git-release-7-2.noarch.rpm && \
    yum install -y epel-release && \
    yum install -y skopeo && \
    yum install -y python36 python36-pip origin-clients openssh-clients openssl git unzip gcc gcc-c++ python36-devel && \
    python3 -m pip install --upgrade pip setuptools && \
    yum clean all

RUN curl https://releases.hashicorp.com/terraform/${TF_VERSION}/terraform_${TF_VERSION}_linux_amd64.zip --output terraform.zip && \
    unzip terraform.zip && \
    mv terraform /usr/local/bin/terraform && \
    rm terraform.zip

RUN curl https://github.com/awslabs/git-secrets/archive/${GIT_SECRETS_VERSION}.tar.gz -L -o git-secrets.tar.gz && \
    tar -zvxf git-secrets.tar.gz git-secrets-${GIT_SECRETS_VERSION}/git-secrets && \
    mv git-secrets-${GIT_SECRETS_VERSION}/git-secrets /usr/local/bin/git-secrets && \
    rm -rf git-secrets*

COPY --from=jsonnet-builder /jsonnet/jsonnet /usr/local/bin/jsonnet
COPY --from=jsonnet-builder /jsonnet-bundler/vendor ${JSONNET_VENDOR_DIR}
RUN find ${JSONNET_VENDOR_DIR} -type d -exec chmod 0755 {} \;

WORKDIR /reconcile

COPY e2e_tests e2e_tests
COPY reconcile reconcile
COPY tools tools
COPY utils utils
COPY templates templates
COPY setup.py .

RUN python3 setup.py install

COPY dockerfiles/hack/run-integration.py /run-integration.py
CMD [ "/run-integration.py" ]
