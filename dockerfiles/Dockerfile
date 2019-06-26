FROM centos:7

ENV LC_ALL=en_US.utf8
ENV LANG=en_US.utf8
ENV TF_VERSION=0.11.13

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

ENV ALERTMANAGER_VERSION 0.17.0
RUN mkdir -p /tmp/alertmanager && cd /tmp/alertmanager && \
    curl -sLO https://github.com/prometheus/alertmanager/releases/download/v${ALERTMANAGER_VERSION}/alertmanager-${ALERTMANAGER_VERSION}.linux-amd64.tar.gz && \
    tar xzvf alertmanager-${ALERTMANAGER_VERSION}.linux-amd64.tar.gz && \
    /bin/cp -avf alertmanager-${ALERTMANAGER_VERSION}.linux-amd64/amtool /usr/bin/

COPY reconcile /reconcile/reconcile
COPY utils /reconcile/utils
COPY terrascript /reconcile/terrascript
COPY setup.py /reconcile

WORKDIR /reconcile

RUN python setup.py install
