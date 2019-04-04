FROM centos:7

ENV LC_ALL=en_US.utf8
ENV LANG=en_US.utf8
ENV TF_VERSION=0.11.13

RUN yum install -y centos-release-openshift-origin && \
    yum install -y epel-release && \
    yum install -y python2-pip origin-clients && \
    pip install --upgrade pip && \
    yum clean all

RUN yum install -y unzip && \
    curl https://releases.hashicorp.com/terraform/${TF_VERSION}/terraform_${TF_VERSION}_linux_amd64.zip --output terraform.zip && \
    unzip terraform.zip && \
    mv terraform /usr/local/bin/terraform && \
    rm terraform.zip

COPY reconcile /reconcile/reconcile
COPY utils /reconcile/utils
COPY terrascript /reconcile/terrascript
COPY setup.py /reconcile

WORKDIR /reconcile

RUN python setup.py install
