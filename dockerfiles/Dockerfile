FROM centos:7 AS jsonnet-builder

ENV GOPATH /go

RUN yum install -y epel-release && \
    yum install -y go

RUN mkdir -p /go && chmod -R 777 /go

ENV JSONNET_VERSION 0.14.0
ENV JSONNET_BUNDLER_VERSION 10e24cb86976782d27a6a821b629919e26bdf882

RUN GO111MODULE=on go get github.com/jsonnet-bundler/jsonnet-bundler/cmd/jb@${JSONNET_BUNDLER_VERSION}
RUN GO111MODULE=on go get github.com/google/go-jsonnet/cmd/jsonnet@v${JSONNET_VERSION}

FROM centos:7

ENV LC_ALL=en_US.utf8
ENV LANG=en_US.utf8
ENV TF_VERSION=0.11.14
ENV JJB_VERSION=2.10.1
ENV GIT_SECRETS_VERSION=1.3.0

RUN yum install -y centos-release-openshift-origin && \
    yum install -y http://opensource.wandisco.com/centos/7/git/x86_64/wandisco-git-release-7-2.noarch.rpm && \
    yum install -y epel-release && \
    yum install -y python36 python36-pip origin-clients openssh-clients openssl git unzip && \
    python3 -m pip install --upgrade pip setuptools && \
    python3 -m pip install jenkins-job-builder==${JJB_VERSION} && \
    yum clean all

RUN curl https://releases.hashicorp.com/terraform/${TF_VERSION}/terraform_${TF_VERSION}_linux_amd64.zip --output terraform.zip && \
    unzip terraform.zip && \
    mv terraform /usr/local/bin/terraform && \
    rm terraform.zip

RUN curl https://github.com/awslabs/git-secrets/archive/${GIT_SECRETS_VERSION}.tar.gz -L -o git-secrets.tar.gz && \
    tar -zvxf git-secrets.tar.gz git-secrets-${GIT_SECRETS_VERSION}/git-secrets && \
    mv git-secrets-${GIT_SECRETS_VERSION}/git-secrets /usr/local/bin/git-secrets && \
    rm -rf git-secrets*
# Add jsonnet deps
COPY --from=jsonnet-builder /go/bin/jb /usr/local/bin/jb
COPY --from=jsonnet-builder /go/bin/jsonnet /usr/local/bin/jsonnet

WORKDIR /reconcile

COPY e2e_tests e2e_tests
COPY reconcile reconcile
COPY tools tools
COPY utils utils
COPY setup.py .
COPY requirements.txt .

RUN python3 -m pip install -r requirements.txt
RUN python3 setup.py install

# required to run ssh on OpenShift
ENV PROD_USER_ID=1001450000
RUN useradd -l -u ${PROD_USER_ID} reconcile
ENV STAGE_USER_ID=1031160000
RUN useradd -l -u ${STAGE_USER_ID} reconcile-stage
