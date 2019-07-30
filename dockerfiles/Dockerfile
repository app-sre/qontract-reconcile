FROM centos:7

ENV LC_ALL=en_US.utf8
ENV LANG=en_US.utf8
ENV TF_VERSION=0.11.14

RUN yum install -y centos-release-openshift-origin && \
    yum install -y epel-release && \
    yum install -y python2-pip origin-clients openssh-clients && \
    pip install --upgrade pip setuptools && \
    yum clean all

RUN yum install -y unzip && \
    curl https://releases.hashicorp.com/terraform/${TF_VERSION}/terraform_${TF_VERSION}_linux_amd64.zip --output terraform.zip && \
    unzip terraform.zip && \
    mv terraform /usr/local/bin/terraform && \
    rm terraform.zip

WORKDIR /reconcile

COPY e2e_tests e2e_tests
COPY reconcile reconcile
COPY utils utils
COPY terrascript terrascript
COPY setup.py .

RUN python setup.py install
