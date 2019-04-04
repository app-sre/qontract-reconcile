FROM centos:7 as terraform-fetcher
ENV TF_VERSION=0.11.13
RUN yum install -y unzip && \
    curl https://releases.hashicorp.com/terraform/${TF_VERSION}/terraform_${TF_VERSION}_linux_amd64.zip --output terraform.zip && \
    unzip terraform.zip


FROM centos:7

ENV LC_ALL=en_US.utf8
ENV LANG=en_US.utf8

RUN yum install -y centos-release-openshift-origin && \
    yum install -y epel-release && \
    yum install -y python2-pip origin-clients && \
    pip install --upgrade pip && \
    yum clean all

COPY --from=terraform-fetcher /terraform /usr/local/bin/terraform
COPY reconcile /reconcile/reconcile
COPY utils /reconcile/utils
COPY setup.py /reconcile

WORKDIR /reconcile

RUN python setup.py install
