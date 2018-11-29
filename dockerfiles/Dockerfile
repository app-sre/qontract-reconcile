FROM centos:7

ENV LC_ALL=en_US.utf8
ENV LANG=en_US.utf8

RUN yum install -y epel-release && \
    yum install -y python2-pip && \
    pip install --upgrade pip

COPY reconcile /reconcile/reconcile
COPY setup.py /reconcile

WORKDIR /reconcile

RUN python setup.py install
