#!/bin/bash

rosa init
rosa create ocm-role --admin -y -m auto
rosa create account-roles --hosted-cp -y -m auto
rosa create user-role -y -m auto

# OIDC config
OIDC_CONFIG_ID="abcdefghijklmnopqrstuvwx"

# operator roles
INSTALLER_ROLE_ARN=$(rosa list account-roles --region us-east-1 -o json | jq '.[] | select(.RoleType == "Installer") | .RoleARN' -r)
rosa create operator-roles --prefix cluster-1 --oidc-config-id ${OIDC_CONFIG_ID} --hosted-cp --installer-role-arn ${INSTALLER_ROLE_ARN} -m auto -y

# cluster creation
BILLING_ACCOUNT_ID=$(aws organizations describe-organization | jq .Organization.MasterAccountId -r)
rosa create cluster --cluster-name=cluster-1 \
    --billing-account ${BILLING_ACCOUNT_ID} \
    --sts \
    --hosted-cp \
    --oidc-config-id ${OIDC_CONFIG_ID} \
    --operator-roles-prefix cluster-1 \
    --subnet-ids subnet-a,subnet-b,subnet-c \
    --region us-east-1 \
    --version 4.10.16 \
    --machine-cidr 10.0.0.0/16 \
    --service-cidr 172.30.0.0/16 \
    --pod-cidr 10.128.0.0/14 \
    --host-prefix 23 \
    --replicas 1 \
    --compute-machine-type m5.xlarge \
    --disable-workload-monitoring \
    --properties provision_shard_id:provision_shard_id \
    --channel-group stable
