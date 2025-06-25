import logging
import operator
import os
import re
from collections.abc import (
    Iterable,
    Iterator,
    Mapping,
    Sequence,
)
from functools import lru_cache
from threading import Lock
from typing import (
    TYPE_CHECKING,
    Any,
    Literal,
    Self,
    cast,
    overload,
)

from boto3 import Session
from botocore.client import BaseClient
from botocore.config import Config
from pydantic import BaseModel
from sretoolbox.utils import threaded

import reconcile.utils.aws_helper as awsh
import reconcile.utils.lean_terraform_client as terraform
from reconcile.utils.secret_reader import SecretReader, SecretReaderBase

if TYPE_CHECKING:
    from mypy_boto3_dynamodb import DynamoDBClient, DynamoDBServiceResource
    from mypy_boto3_ec2 import (
        EC2Client,
        EC2ServiceResource,
    )
    from mypy_boto3_ec2.type_defs import (
        FilterTypeDef,
        ImageTypeDef,
        LaunchPermissionModificationsTypeDef,
        NetworkInterfaceTypeDef,
        RouteTableTypeDef,
        SubnetTypeDef,
        TagTypeDef,
        TransitGatewayTypeDef,
        TransitGatewayVpcAttachmentTypeDef,
        VpcEndpointTypeDef,
        VpcTypeDef,
    )
    from mypy_boto3_ecr import ECRClient
    from mypy_boto3_elb import ElasticLoadBalancingClient
    from mypy_boto3_elb.type_defs import (
        LoadBalancerDescriptionTypeDef,
        TagDescriptionTypeDef,
    )
    from mypy_boto3_iam import IAMClient, IAMServiceResource
    from mypy_boto3_iam.type_defs import AccessKeyMetadataTypeDef
    from mypy_boto3_logs import CloudWatchLogsClient
    from mypy_boto3_logs.type_defs import LogGroupTypeDef
    from mypy_boto3_organizations import OrganizationsClient
    from mypy_boto3_rds import RDSClient
    from mypy_boto3_rds.type_defs import (
        DBInstanceMessageTypeDef,
        DBRecommendationsMessageTypeDef,
        UpgradeTargetTypeDef,
    )
    from mypy_boto3_route53 import Route53Client
    from mypy_boto3_route53.type_defs import (
        HostedZoneTypeDef,
        ResourceRecordSetTypeDef,
        ResourceRecordTypeDef,
    )
    from mypy_boto3_s3 import S3Client, S3ServiceResource
    from mypy_boto3_sqs import SQSClient, SQSServiceResource
    from mypy_boto3_sts import STSClient
    from mypy_boto3_support import SupportClient
    from mypy_boto3_support.type_defs import CaseDetailsTypeDef

else:
    AccessKeyMetadataTypeDef = CaseDetailsTypeDef = CloudWatchLogsClient = (
        DBInstanceMessageTypeDef
    ) = DBRecommendationsMessageTypeDef = DynamoDBClient = DynamoDBServiceResource = (
        EC2Client
    ) = EC2ServiceResource = ECRClient = ElasticLoadBalancingClient = FilterTypeDef = (
        HostedZoneTypeDef
    ) = IAMClient = IAMServiceResource = ImageTypeDef = (
        LaunchPermissionModificationsTypeDef
    ) = LogGroupTypeDef = OrganizationsClient = RDSClient = ResourceRecordSetTypeDef = (
        ResourceRecordTypeDef
    ) = Route53Client = RouteTableTypeDef = S3Client = S3ServiceResource = SQSClient = (
        SQSServiceResource
    ) = STSClient = SubnetTypeDef = SupportClient = TagTypeDef = (
        TransitGatewayTypeDef
    ) = TransitGatewayVpcAttachmentTypeDef = UpgradeTargetTypeDef = (
        VpcEndpointTypeDef
    ) = VpcTypeDef = NetworkInterfaceTypeDef = LoadBalancerDescriptionTypeDef = (
        TagDescriptionTypeDef
    ) = object


class InvalidResourceTypeError(Exception):
    pass


class MissingARNError(Exception):
    pass


KeyStatus = Literal["Active", "Inactive"]

GOVCLOUD_PARTITION = "aws-us-gov"


class AmiTag(BaseModel):
    name: str
    value: str


SERVICE_NAME = Literal[
    "dynamodb",
    "ec2",
    "ecr",
    "elb",
    "iam",
    "logs",
    "organizations",
    "rds",
    "route53",
    "s3",
    "sqs",
    "sts",
    "support",
]
RESOURCE_NAME = Literal[
    "dynamodb",
    "ec2",
    "iam",
    "s3",
    "sqs",
]


class AWSApi:
    """Wrapper around AWS SDK"""

    def __init__(
        self,
        thread_pool_size: int,
        accounts: Iterable[awsh.Account],
        settings: Mapping | None = None,
        secret_reader: SecretReaderBase | None = None,
        init_ecr_auth_tokens: bool = False,
        init_users: bool = True,
    ) -> None:
        self._session_clients: list[BaseClient] = []
        self.thread_pool_size = thread_pool_size
        if secret_reader:
            self.secret_reader = secret_reader
        else:
            self.secret_reader = SecretReader(settings=settings)
        self.init_sessions(accounts)
        if init_ecr_auth_tokens:
            self.init_ecr_auth_tokens(accounts)
        self._lock = Lock()

        # store the app-interface accounts in a dictionary indexed by name
        self.accounts = {acc["name"]: acc for acc in accounts}

        # Setup caches on the instance itself to avoid leak
        # https://stackoverflow.com/questions/33672412/python-functools-lru-cache-with-class-methods-release-object
        # using @lru_cache decorators on methods would lek AWSApi instances
        # since the cache keeps a reference to self.
        self._get_assume_role_session = lru_cache()(self._get_assume_role_session)  # type: ignore[method-assign]
        self._get_session_resource = lru_cache()(self._get_session_resource)  # type: ignore[method-assign, assignment]
        self.get_account_amis = lru_cache()(self.get_account_amis)  # type: ignore[method-assign]
        self.get_account_vpcs = lru_cache()(self.get_account_vpcs)  # type: ignore[method-assign]
        self.get_session_client = lru_cache()(self.get_session_client)  # type: ignore[method-assign, assignment]
        self.get_transit_gateway_vpc_attachments = lru_cache()(  # type: ignore[method-assign]
            self.get_transit_gateway_vpc_attachments
        )
        self.get_transit_gateways = lru_cache()(self.get_transit_gateways)  # type: ignore[method-assign]
        self.get_vpc_default_sg_id = lru_cache()(self.get_vpc_default_sg_id)  # type: ignore[method-assign]
        self.get_vpc_route_tables = lru_cache()(self.get_vpc_route_tables)  # type: ignore[method-assign]
        self.get_vpc_subnets = lru_cache()(self.get_vpc_subnets)  # type: ignore[method-assign]
        self._get_vpc_endpoints = lru_cache()(self._get_vpc_endpoints)  # type: ignore[method-assign]
        self.get_network_interfaces = lru_cache()(self.get_network_interfaces)  # type: ignore[method-assign]
        self.get_load_balancers = lru_cache()(self.get_load_balancers)  # type: ignore[method-assign]
        self.get_load_balancer_tags = lru_cache()(self.get_load_balancer_tags)  # type: ignore[method-assign]

        if init_users:
            self.init_users()

    def init_sessions(self, accounts: Iterable[awsh.Account]) -> None:
        results = threaded.run(
            awsh.get_tf_secrets,
            accounts,
            self.thread_pool_size,
            secret_reader=self.secret_reader,
        )
        self.sessions: dict[str, Session] = {}
        for account_name, secret in results:
            account = awsh.get_account(accounts, account_name)
            access_key = secret["aws_access_key_id"]
            secret_key = secret["aws_secret_access_key"]
            region_name = account["resourcesDefaultRegion"]
            self.use_fips = False

            # ensure that govcloud accounts use FIPs endpoints
            if "partition" in account and account["partition"] == GOVCLOUD_PARTITION:
                logging.debug(f"FIPS endpoint enabled for AWS account: {account_name}")
                self.use_fips = True

            session = Session(
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region_name,
            )
            self.sessions[account_name] = session

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.cleanup()

    def cleanup(self) -> None:
        """
        Close all session clients
        :return:
        """
        for client in self._session_clients:
            client.close()

    def get_session(self, account: str) -> Session:
        return self.sessions[account]

    @overload
    def get_session_client(
        self,
        session: Session,
        service_name: Literal["ec2"],
        region_name: str | None = None,
    ) -> EC2Client: ...

    @overload
    def get_session_client(
        self,
        session: Session,
        service_name: Literal["elb"],
        region_name: str | None = None,
    ) -> ElasticLoadBalancingClient: ...

    @overload
    def get_session_client(
        self,
        session: Session,
        service_name: Literal["route53"],
        region_name: str | None = None,
    ) -> Route53Client: ...

    @overload
    def get_session_client(
        self,
        session: Session,
        service_name: Literal["rds"],
        region_name: str | None = None,
    ) -> RDSClient: ...

    @overload
    def get_session_client(
        self,
        session: Session,
        service_name: Literal["logs"],
        region_name: str | None = None,
    ) -> CloudWatchLogsClient: ...

    @overload
    def get_session_client(
        self,
        session: Session,
        service_name: Literal["organizations"],
        region_name: str | None = None,
    ) -> OrganizationsClient: ...

    @overload
    def get_session_client(
        self,
        session: Session,
        service_name: Literal["s3"],
        region_name: str | None = None,
    ) -> S3Client: ...

    @overload
    def get_session_client(
        self,
        session: Session,
        service_name: Literal["iam"],
        region_name: str | None = None,
    ) -> IAMClient: ...

    @overload
    def get_session_client(
        self,
        session: Session,
        service_name: Literal["sqs"],
        region_name: str | None = None,
    ) -> SQSClient: ...

    @overload
    def get_session_client(
        self,
        session: Session,
        service_name: Literal["dynamodb"],
        region_name: str | None = None,
    ) -> DynamoDBClient: ...

    @overload
    def get_session_client(
        self,
        session: Session,
        service_name: Literal["ecr"],
        region_name: str | None = None,
    ) -> ECRClient: ...

    @overload
    def get_session_client(
        self,
        session: Session,
        service_name: Literal["support"],
        region_name: str | None = None,
    ) -> SupportClient: ...

    @overload
    def get_session_client(
        self,
        session: Session,
        service_name: Literal["sts"],
        region_name: str | None = None,
    ) -> STSClient: ...

    def get_session_client(
        self,
        session: Session,
        service_name: SERVICE_NAME,
        region_name: str | None = None,
    ) -> (
        CloudWatchLogsClient
        | DynamoDBClient
        | EC2Client
        | ECRClient
        | ElasticLoadBalancingClient
        | IAMClient
        | OrganizationsClient
        | RDSClient
        | Route53Client
        | S3Client
        | SQSClient
        | STSClient
        | SupportClient
    ):
        region = region_name or session.region_name
        client = session.client(
            service_name,
            region_name=region,
            config=Config(use_fips_endpoint=self.use_fips),
        )
        self._session_clients.append(client)
        return client

    @overload
    @staticmethod
    def _get_session_resource(
        session: Session,
        service_name: Literal["dynamodb"],
        region_name: str | None = None,
    ) -> DynamoDBServiceResource: ...

    @overload
    @staticmethod
    def _get_session_resource(
        session: Session,
        service_name: Literal["ec2"],
        region_name: str | None = None,
    ) -> EC2ServiceResource: ...

    @overload
    @staticmethod
    def _get_session_resource(
        session: Session,
        service_name: Literal["iam"],
        region_name: str | None = None,
    ) -> IAMServiceResource: ...

    @overload
    @staticmethod
    def _get_session_resource(
        session: Session,
        service_name: Literal["s3"],
        region_name: str | None = None,
    ) -> S3ServiceResource: ...

    @overload
    @staticmethod
    def _get_session_resource(
        session: Session,
        service_name: Literal["sqs"],
        region_name: str | None = None,
    ) -> SQSServiceResource: ...

    @staticmethod
    def _get_session_resource(
        session: Session, service_name: RESOURCE_NAME, region_name: str | None = None
    ) -> (
        DynamoDBServiceResource
        | EC2ServiceResource
        | IAMServiceResource
        | S3ServiceResource
        | SQSServiceResource
    ):
        region = region_name or session.region_name
        return session.resource(service_name, region_name=region)

    def _account_ec2_client(
        self, account_name: str, region_name: str | None = None
    ) -> EC2Client:
        session = self.get_session(account_name)
        return self.get_session_client(session, "ec2", region_name)

    def _account_ec2_resource(
        self, account_name: str, region_name: str | None = None
    ) -> EC2ServiceResource:
        session = self.get_session(account_name)
        return self._get_session_resource(session, "ec2", region_name)

    def _account_route53_client(
        self, account_name: str, region_name: str | None = None
    ) -> Route53Client:
        session = self.get_session(account_name)
        return self.get_session_client(session, "route53", region_name)

    def _account_rds_client(
        self, account_name: str, region_name: str | None = None
    ) -> RDSClient:
        session = self.get_session(account_name)
        return self.get_session_client(session, "rds", region_name)

    def _account_cloudwatch_client(
        self, account_name: str, region_name: str | None = None
    ) -> CloudWatchLogsClient:
        session = self.get_session(account_name)
        return self.get_session_client(session, "logs", region_name)

    def _account_organizations_client(
        self, account_name: str, region_name: str | None = None
    ) -> OrganizationsClient:
        session = self.get_session(account_name)
        return self.get_session_client(session, "organizations", region_name)

    def _account_s3_client(
        self, account_name: str, region_name: str | None = None
    ) -> S3Client:
        session = self.get_session(account_name)
        return cast(S3Client, self.get_session_client(session, "s3", region_name))

    def init_users(self) -> None:
        self.users = {}
        for account, s in self.sessions.items():
            iam = self.get_session_client(s, "iam")
            users = self.paginate(iam, "list_users", "Users")
            users = [u["UserName"] for u in users]
            self.users[account] = users

    @staticmethod
    def paginate(
        client: BaseClient, method: str, key: str, params: Mapping | None = None
    ) -> Iterable:
        """paginate returns an aggregated list of the specified key
        from all pages returned by executing the client's specified method."""
        if params is None:
            params = {}
        paginator = client.get_paginator(method)
        return [
            values
            for page in paginator.paginate(**params)
            for values in page.get(key, [])
        ]

    @staticmethod
    def determine_key_type(iam: IAMClient, user: str) -> str:
        tags = iam.list_user_tags(UserName=user)["Tags"]
        managed_by_integration_tag = [
            t["Value"] for t in tags if t["Key"] == "managed_by_integration"
        ]
        # if this key belongs to a user without tags, i.e. not
        # managed by an integration, this key is probably created
        # manually. disable it to leave a trace
        if not managed_by_integration_tag:
            return "unmanaged"
        # if this key belongs to a user created by the
        # 'terraform-users' integration, we just delete the key
        if managed_by_integration_tag[0] == "terraform_users":
            return "user"
        # if this key belongs to a user created by the
        # 'terraform-resources' integration, we remove
        # the key from terraform state and let it create
        # a new one on its own
        if managed_by_integration_tag[0] == "terraform_resources":
            return "service_account"

        huh = (
            f"unrecognized managed_by_integration tag: {managed_by_integration_tag[0]}"
        )
        raise InvalidResourceTypeError(huh)

    def delete_keys(
        self,
        dry_run: bool,
        keys_to_delete: Mapping,
        working_dirs: Mapping[str, str],
        disable_service_account_keys: bool,
    ) -> tuple[bool, bool]:
        error = False
        service_account_recycle_complete = True
        users_keys = self.get_users_keys()
        for account, s in self.sessions.items():
            iam = self.get_session_client(s, "iam")
            keys = keys_to_delete.get(account, [])
            for key in keys:
                user_and_user_keys = [
                    (user, user_keys)
                    for user, user_keys in users_keys[account].items()
                    if key in user_keys
                ]
                if not user_and_user_keys:
                    continue

                if len(user_and_user_keys) > 1:
                    raise RuntimeError(
                        f"key {key} returned multiple users: {user_and_user_keys}"
                    )
                user = user_and_user_keys[0][0]
                user_keys = user_and_user_keys[0][1]
                key_type = self.determine_key_type(iam, user)
                key_status = self.get_user_key_status(iam, user, key)
                if key_type == "unmanaged" and key_status == "Active":
                    logging.info(["disable_key", account, user, key])

                    if not dry_run:
                        iam.update_access_key(
                            UserName=user, AccessKeyId=key, Status="Inactive"
                        )
                elif key_type == "user":
                    logging.info(["delete_key", account, user, key])

                    if not dry_run:
                        iam.delete_access_key(UserName=user, AccessKeyId=key)
                elif key_type == "service_account":
                    # if key is disabled - delete it
                    # this will happen after terraform-resources ran,
                    # provisioned a new key, updated the output Secret,
                    # recycled the pods and disabled the key.
                    if key_status == "Inactive":
                        logging.info(["delete_inactive_key", account, user, key])
                        if not dry_run:
                            iam.delete_access_key(UserName=user, AccessKeyId=key)
                        continue

                    # if key is active and it is the only one -
                    # remove it from terraform state. terraform-resources
                    # will provision a new one.
                    # may be a race condition here. TODO: check it
                    if len(user_keys) == 1:
                        service_account_recycle_complete = False
                        logging.info(["remove_from_state", account, user, key])
                        if not dry_run:
                            terraform.state_rm_access_key(working_dirs, account, user)

                    # if user has 2 keys and we remove the key from
                    # terraform state, terraform-resources will not
                    # be able to provision a new key - limbo.
                    # this state should happen when terraform-resources
                    # is running, provisioned a new key,
                    # but did not disable the old key yet.
                    if len(user_keys) == 2:
                        # if true, this is a call made by terraform-resources
                        # itself. disable the key and proceed. the key will be
                        # deleted in a following iteration of aws-iam-keys.
                        if disable_service_account_keys:
                            service_account_recycle_complete = False
                            logging.info(["disable_key", account, user, key])

                            if not dry_run:
                                iam.update_access_key(
                                    UserName=user, AccessKeyId=key, Status="Inactive"
                                )
                        else:
                            msg = "user {} has 2 keys, skipping to avoid error"
                            logging.error(msg.format(user))
                            error = True

        return error, service_account_recycle_complete

    def get_users_keys(self) -> dict:
        users_keys = {}
        for account, s in self.sessions.items():
            iam = self.get_session_client(s, "iam")
            users_keys[account] = {
                user: self.get_user_keys(iam, user) for user in self.users[account]
            }

        return users_keys

    def reset_password(self, account: str, user_name: str) -> None:
        s = self.sessions[account]
        iam = self.get_session_client(s, "iam")
        iam.delete_login_profile(UserName=user_name)

    def reset_mfa(self, account: str, user_name: str) -> None:
        s = self.sessions[account]
        iam = self.get_session_client(s, "iam")
        mfa_devices = iam.list_mfa_devices(UserName=user_name)["MFADevices"]
        for d in mfa_devices:
            serial_number = d["SerialNumber"]
            iam.deactivate_mfa_device(UserName=user_name, SerialNumber=serial_number)
            iam.delete_virtual_mfa_device(SerialNumber=serial_number)

    @staticmethod
    def _get_user_key_list(iam: IAMClient, user: str) -> list[AccessKeyMetadataTypeDef]:
        try:
            return iam.list_access_keys(UserName=user)["AccessKeyMetadata"]
        except iam.exceptions.NoSuchEntityException:
            return []

    def get_user_keys(self, iam: IAMClient, user: str) -> list[str]:
        key_list = self._get_user_key_list(iam, user)
        return [uk["AccessKeyId"] for uk in key_list]

    def get_user_key_status(self, iam: IAMClient, user: str, key: str) -> KeyStatus:
        key_list = self._get_user_key_list(iam, user)
        return next(k["Status"] for k in key_list if k["AccessKeyId"] == key)

    def get_support_cases(self) -> dict[str, list[CaseDetailsTypeDef]]:
        all_support_cases = {}
        for account, s in self.sessions.items():
            if not self.accounts[account].get("premiumSupport"):
                continue
            support_region = self._get_aws_support_api_region(
                self.accounts[account]["partition"]
            )
            try:
                support = self.get_session_client(s, "support", support_region)
                support_cases = support.describe_cases(
                    includeResolvedCases=True, includeCommunications=True
                )["cases"]
                all_support_cases[account] = support_cases
            except Exception as e:
                msg = "[{}] error getting support cases. details: {}"
                logging.error(msg.format(account, str(e)))

        return all_support_cases

    @staticmethod
    def _get_aws_support_api_region(partition: str) -> str:
        """
        The AWS support API is only available in a single region for the aws and
        aws-us-gov partitions.

        https://docs.aws.amazon.com/general/latest/gr/awssupport.html
        """
        if partition == GOVCLOUD_PARTITION:
            support_region = "us-gov-west-1"
        else:
            support_region = "us-east-1"

        return support_region

    def init_ecr_auth_tokens(self, accounts: Iterable[awsh.Account]) -> None:
        accounts_with_ecr = [a for a in accounts if a.get("ecrs")]
        if not accounts_with_ecr:
            return

        auth_tokens = {}
        results = threaded.run(
            awsh.get_tf_secrets,
            accounts_with_ecr,
            self.thread_pool_size,
            secret_reader=self.secret_reader,
        )
        account_secrets = dict(results)
        for account in accounts_with_ecr:
            account_name = account["name"]
            account_secret = account_secrets[account_name]
            access_key = account_secret["aws_access_key_id"]
            secret_key = account_secret["aws_secret_access_key"]

            ecrs = account["ecrs"]
            for ecr in ecrs:
                region_name = ecr["region"]
                session = Session(
                    aws_access_key_id=access_key,
                    aws_secret_access_key=secret_key,
                    region_name=region_name,
                )
                client = self.get_session_client(session, "ecr")
                token = client.get_authorization_token()
                auth_tokens[f"{account_name}/{region_name}"] = token

        self.auth_tokens = auth_tokens

    @staticmethod
    def _get_account_assume_data(
        account: awsh.Account,
    ) -> tuple[str, str | None, str]:
        """
        returns mandatory data to be able to assume a role with this account:
        (account_name, assume_role, assume_region)
        assume_role may be None for ROSA (CCS) clusters where we own the account
        """
        required_keys = ["name", "assume_region"]
        ok = all(elem in account for elem in required_keys)
        if not ok:
            account_name = account.get("name")
            raise KeyError(f"[{account_name}] account is missing required keys")
        return (account["name"], account.get("assume_role"), account["assume_region"])

    @staticmethod
    def _get_assume_role_session(
        sts: STSClient, account_name: str, assume_role: str, assume_region: str
    ) -> Session:
        """
        Returns a session for a supplied role to assume:

        :param sts:           boto3 sts client
        :param account_name:  name of the AWS account
        :param assume_role:   role to assume to get access
                              to the cluster's AWS account
        :param assume_region: region in which to operate
        """

        if not assume_role:
            raise MissingARNError(
                f"Could not find Role ARN {assume_role} on account "
                f"{account_name}. This is likely caused by a missing "
                "awsInfrastructureAccess section."
            )
        role_name = assume_role.split("/")[1]
        response = sts.assume_role(RoleArn=assume_role, RoleSessionName=role_name)
        credentials = response["Credentials"]

        assumed_session = Session(
            aws_access_key_id=credentials["AccessKeyId"],
            aws_secret_access_key=credentials["SecretAccessKey"],
            aws_session_token=credentials["SessionToken"],
            region_name=assume_region,
        )

        return assumed_session

    @overload
    def _get_assumed_role_client(
        self,
        account_name: str,
        assume_role: str | None,
        assume_region: str,
        client_type: Literal["logs"],
    ) -> CloudWatchLogsClient: ...

    @overload
    def _get_assumed_role_client(
        self,
        account_name: str,
        assume_role: str | None,
        assume_region: str,
        client_type: Literal["dynamodb"],
    ) -> DynamoDBClient: ...

    @overload
    def _get_assumed_role_client(
        self,
        account_name: str,
        assume_role: str | None,
        assume_region: str,
        client_type: Literal["ec2"],
    ) -> EC2Client: ...

    @overload
    def _get_assumed_role_client(
        self,
        account_name: str,
        assume_role: str | None,
        assume_region: str,
        client_type: Literal["ecr"],
    ) -> ECRClient: ...

    @overload
    def _get_assumed_role_client(
        self,
        account_name: str,
        assume_role: str | None,
        assume_region: str,
        client_type: Literal["elb"],
    ) -> ElasticLoadBalancingClient: ...

    @overload
    def _get_assumed_role_client(
        self,
        account_name: str,
        assume_role: str | None,
        assume_region: str,
        client_type: Literal["iam"],
    ) -> IAMClient: ...

    @overload
    def _get_assumed_role_client(
        self,
        account_name: str,
        assume_role: str | None,
        assume_region: str,
        client_type: Literal["organizations"],
    ) -> OrganizationsClient: ...

    @overload
    def _get_assumed_role_client(
        self,
        account_name: str,
        assume_role: str | None,
        assume_region: str,
        client_type: Literal["rds"],
    ) -> RDSClient: ...

    @overload
    def _get_assumed_role_client(
        self,
        account_name: str,
        assume_role: str | None,
        assume_region: str,
        client_type: Literal["route53"],
    ) -> Route53Client: ...

    @overload
    def _get_assumed_role_client(
        self,
        account_name: str,
        assume_role: str | None,
        assume_region: str,
        client_type: Literal["s3"],
    ) -> S3Client: ...

    @overload
    def _get_assumed_role_client(
        self,
        account_name: str,
        assume_role: str | None,
        assume_region: str,
        client_type: Literal["sqs"],
    ) -> SQSClient: ...

    @overload
    def _get_assumed_role_client(
        self,
        account_name: str,
        assume_role: str | None,
        assume_region: str,
        client_type: Literal["sts"],
    ) -> STSClient: ...

    @overload
    def _get_assumed_role_client(
        self,
        account_name: str,
        assume_role: str | None,
        assume_region: str,
        client_type: Literal["support"],
    ) -> SupportClient: ...

    def _get_assumed_role_client(
        self,
        account_name: str,
        assume_role: str | None,
        assume_region: str,
        client_type: SERVICE_NAME = "ec2",
    ) -> (
        CloudWatchLogsClient
        | DynamoDBClient
        | EC2Client
        | ECRClient
        | ElasticLoadBalancingClient
        | IAMClient
        | OrganizationsClient
        | RDSClient
        | Route53Client
        | S3Client
        | SQSClient
        | STSClient
        | SupportClient
    ):
        session = self.get_session(account_name)
        if not assume_role:
            return self.get_session_client(
                session, client_type, region_name=assume_region
            )
        sts = self.get_session_client(session, "sts")
        assumed_session = self._get_assume_role_session(
            sts, account_name, assume_role, assume_region
        )
        return self.get_session_client(assumed_session, client_type)

    @staticmethod
    def get_account_vpcs(ec2: EC2Client) -> list[VpcTypeDef]:
        vpcs = ec2.describe_vpcs()
        return vpcs.get("Vpcs", [])

    @staticmethod
    def get_account_amis(ec2: EC2Client, owner: str) -> list[ImageTypeDef]:
        amis = ec2.describe_images(Owners=[owner])
        return amis.get("Images", [])

    # filters a list of aws resources according to tags
    @staticmethod
    def filter_on_tags(
        items: Iterable[Any], tags: Mapping[str, str] | None = None
    ) -> list[Any]:
        if tags is None:
            tags = {}
        res = []
        for item in items:
            tags_dict = {t["Key"]: t["Value"] for t in item.get("Tags", [])}
            if all(tags_dict.get(k) == values for k, values in tags.items()):
                res.append(item)
        return res

    @staticmethod
    def get_vpc_route_tables(vpc_id: str, ec2: EC2Client) -> list[RouteTableTypeDef]:
        rts = ec2.describe_route_tables(
            Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
        )
        return rts.get("RouteTables", [])

    @staticmethod
    def get_vpc_subnets(vpc_id: str, ec2: EC2Client) -> list[SubnetTypeDef]:
        subnets = ec2.describe_subnets(Filters=[{"Name": "vpc-id", "Values": [vpc_id]}])
        return subnets.get("Subnets", [])

    def get_cluster_vpc_details(
        self,
        account: awsh.Account,
        route_tables: bool = False,
        subnets: bool = False,
        hcp_vpc_endpoint_sg: bool = False,
    ) -> tuple[str | None, list[str] | None, list[dict[str, str]] | None, str | None]:
        """
        Returns a cluster VPC details:
            - VPC ID
            - Route table IDs (optional)
            - Subnets list including Subnet ID and Subnet Availability zone
            - VPC Endpoint default security group of the private API router (optional)
        :param account: a dictionary containing the following keys:
                        - name - name of the AWS account
                        - assume_role - role to assume to get access
                                        to the cluster's AWS account
                        - assume_region - region in which to operate
                        - assume_cidr - CIDR block of the cluster to
                                        use to find the matching VPC
        """
        assume_role_data = self._get_account_assume_data(account)
        assumed_ec2 = self._get_assumed_role_client(
            account_name=assume_role_data[0],
            assume_role=assume_role_data[1],
            assume_region=assume_role_data[2],
            client_type="ec2",
        )
        vpcs = self.get_account_vpcs(assumed_ec2)
        vpc_id = None
        for vpc in vpcs:
            if vpc["CidrBlock"] == account["assume_cidr"]:
                vpc_id = vpc["VpcId"]
                break

        route_table_ids = None
        subnets_id_az = None
        api_security_group_id = None
        if vpc_id:
            if route_tables:
                vpc_route_tables = self.get_vpc_route_tables(vpc_id, assumed_ec2)
                route_table_ids = [rt["RouteTableId"] for rt in vpc_route_tables]
            if subnets:
                vpc_subnets = self.get_vpc_subnets(vpc_id, assumed_ec2)
                subnets_id_az = [
                    {"id": s["SubnetId"], "az": s["AvailabilityZone"]}
                    for s in vpc_subnets
                ]
            if hcp_vpc_endpoint_sg:
                api_security_group_id = self._get_api_security_group_id(
                    assumed_ec2, vpc_id
                )

        return vpc_id, route_table_ids, subnets_id_az, api_security_group_id

    def _get_api_security_group_id(
        self, assumed_ec2: EC2Client, vpc_id: str
    ) -> str | None:
        endpoints = AWSApi._get_vpc_endpoints(
            [
                {"Name": "vpc-id", "Values": [vpc_id]},
                {
                    "Name": "tag:AWSEndpointService",
                    "Values": ["private-router"],
                },
            ],
            assumed_ec2,
        )
        if not endpoints:
            return None
        if len(endpoints) > 1:
            raise ValueError(
                f"exactly one VPC endpoint for private API router in VPC {vpc_id} expected but {len(endpoints)} found"
            )
        endpoint = endpoints[0]
        vpc_endpoint_id = endpoint["VpcEndpointId"]
        # https://github.com/openshift/hypershift/blob/c855f68e84e78924ccc9c2132b75dc7e30c4e1d8/control-plane-operator/controllers/hostedcontrolplane/hostedcontrolplane_controller.go#L4243
        # https://github.com/openshift/hypershift/blob/2569f3353ef5ac0858eace9ee77310c3cc38b8e0/control-plane-operator/controllers/awsprivatelink/awsprivatelink_controller.go#L787
        security_groups = [
            sg
            for sg in endpoint["Groups"]
            if sg["GroupName"].endswith("-default-sg")
            or sg["GroupName"].endswith("-vpce-private-router")
        ]
        if len(security_groups) != 1:
            raise ValueError(
                f"exactly one VPC endpoint default security group for private API router {vpc_endpoint_id} "
                f"in VPC {vpc_id} expected but {len(security_groups)} found"
            )
        return security_groups[0]["GroupId"]

    def get_cluster_nat_gateways_egress_ips(
        self, account: dict[str, Any], vpc_id: str
    ) -> set[str]:
        assume_role_data = self._get_account_assume_data(account)
        assumed_ec2 = self._get_assumed_role_client(
            account_name=assume_role_data[0],
            assume_role=assume_role_data[1],
            assume_region=assume_role_data[2],
            client_type="ec2",
        )
        nat_gateways = assumed_ec2.describe_nat_gateways()
        egress_ips: set[str] = set()
        for nat in nat_gateways.get("NatGateways") or []:
            if nat["VpcId"] != vpc_id:
                continue
            egress_ips.update(
                address["PublicIp"] for address in nat["NatGatewayAddresses"]
            )

        return egress_ips

    def get_vpcs_details(
        self,
        account: awsh.Account,
        tags: Mapping[str, str] | None = None,
        route_tables: bool = False,
    ) -> list[dict[str, Any]]:
        results = []
        ec2 = self._account_ec2_client(account["name"])
        regions = [r["RegionName"] for r in ec2.describe_regions()["Regions"]]
        for region_name in regions:
            ec2 = self._account_ec2_client(account["name"], region_name)
            vpcs = self.get_account_vpcs(ec2)
            vpcs = self.filter_on_tags(vpcs, tags)
            for vpc in vpcs:
                vpc_id = vpc["VpcId"]
                cidr_block = vpc["CidrBlock"]
                route_table_ids = None
                if route_tables:
                    vpc_route_tables = self.get_vpc_route_tables(vpc_id, ec2)
                    route_table_ids = [rt["RouteTableId"] for rt in vpc_route_tables]
                item = {
                    "vpc_id": vpc_id,
                    "region": region_name,
                    "cidr_block": cidr_block,
                    "route_table_ids": route_table_ids,
                }
                results.append(item)

        return results

    def get_vpc_route_table_ids(
        self, account: dict[str, Any], vpc_id: str, region_name: str
    ) -> list[str]:
        ec2 = self._account_ec2_client(account["name"], region_name)
        vpc_route_tables = self.get_vpc_route_tables(vpc_id, ec2)
        return [rt["RouteTableId"] for rt in vpc_route_tables]

    @staticmethod
    def _filter_amis(
        images: Iterable[ImageTypeDef], regex: str
    ) -> list[dict[str, Any]]:
        results = []
        pattern = re.compile(regex)
        for i in images:
            if not re.search(pattern, i["Name"]):
                continue
            if i["State"] != "available":
                continue
            item = {"image_id": i["ImageId"], "tags": i.get("Tags", [])}
            results.append(item)

        return results

    def get_amis_details(
        self,
        account: Mapping[str, Any],
        owner_account: Mapping[str, Any],
        regex: str,
        region: str | None = None,
    ) -> list[dict[str, Any]]:
        ec2 = self._account_ec2_client(account["name"], region_name=region)
        images = self.get_account_amis(ec2, owner=owner_account["uid"])
        return self._filter_amis(images, regex)

    def share_ami(
        self,
        account: Mapping[str, Any],
        share_account_uid: str,
        image_id: str,
        region: str | None = None,
    ) -> None:
        ec2 = self._account_ec2_resource(account["name"], region)
        image = ec2.Image(image_id)
        launch_permission: LaunchPermissionModificationsTypeDef = {
            "Add": [{"UserId": share_account_uid}]
        }
        image.modify_attribute(LaunchPermission=launch_permission)

    @staticmethod
    def _normalize_log_group_arn(arn: str) -> str:
        # DescribeLogGroups response arn has additional :* at the end
        return arn.rstrip(":*")

    def create_cloudwatch_tag(
        self,
        account_name: str,
        arn: str,
        new_tag: dict[str, str],
        region_name: str | None = None,
    ) -> None:
        client = self._account_cloudwatch_client(account_name, region_name=region_name)
        client.tag_resource(
            resourceArn=self._normalize_log_group_arn(arn),
            tags=new_tag,
        )

    def get_cloudwatch_log_groups(
        self,
        account_name: str,
        region_name: str | None = None,
    ) -> Iterator[LogGroupTypeDef]:
        client = self._account_cloudwatch_client(account_name, region_name=region_name)
        paginator = client.get_paginator("describe_log_groups")
        for page in paginator.paginate():
            yield from page["logGroups"]

    def get_cloudwatch_log_group_tags(
        self,
        account_name: str,
        arn: str,
        region_name: str | None = None,
    ) -> dict[str, str]:
        client = self._account_cloudwatch_client(account_name, region_name=region_name)
        tags = client.list_tags_for_resource(
            resourceArn=self._normalize_log_group_arn(arn),
        )
        return tags.get("tags", {})

    def set_cloudwatch_log_retention(
        self,
        account_name: str,
        group_name: str,
        retention_days: int,
        region_name: str | None = None,
    ) -> None:
        client = self._account_cloudwatch_client(account_name, region_name=region_name)
        client.put_retention_policy(
            logGroupName=group_name, retentionInDays=retention_days
        )

    def delete_cloudwatch_log_group(
        self,
        account_name: str,
        group_name: str,
        region_name: str | None = None,
    ) -> None:
        client = self._account_cloudwatch_client(account_name, region_name=region_name)
        client.delete_log_group(logGroupName=group_name)

    def create_tag(
        self, account: Mapping[str, Any], resource_id: str, tag: Mapping[str, str]
    ) -> None:
        ec2 = self._account_ec2_client(account["name"])
        tag_type_def: TagTypeDef = {"Key": tag["Key"], "Value": tag["Value"]}
        ec2.create_tags(Resources=[resource_id], Tags=[tag_type_def])

    def get_alb_network_interface_ips(
        self, account: awsh.Account, service_name: str
    ) -> set[str]:
        assumed_role_data = self._get_account_assume_data(account)
        ec2_client = self._get_assumed_role_client(
            account_name=assumed_role_data[0],
            assume_role=assumed_role_data[1],
            assume_region=assumed_role_data[2],
            client_type="ec2",
        )
        elb_client = self._get_assumed_role_client(
            account_name=assumed_role_data[0],
            assume_role=assumed_role_data[1],
            assume_region=assumed_role_data[2],
            client_type="elb",
        )
        service_tag = {"Key": "kubernetes.io/service-name", "Value": service_name}
        nis = self.get_network_interfaces(ec2_client)
        lbs = self.get_load_balancers(elb_client)
        result_ips = set()
        for lb in lbs:
            lb_name = lb["LoadBalancerName"]
            tag_descriptions = self.get_load_balancer_tags(
                elb=elb_client, lb_name=lb_name
            )
            for td in tag_descriptions:
                tags = td["Tags"]
                if service_tag not in tags:
                    continue
                # found a load balancer we want to work with
                # find all network interfaces related to it
                for ni in nis:
                    if ni["Description"] != f"ELB {lb_name}":
                        continue
                    if ni["Status"] != "in-use":
                        continue
                    # found a network interface!
                    ip = ni["PrivateIpAddress"]
                    result_ips.add(ip)

        return result_ips

    @staticmethod
    def get_network_interfaces(ec2: EC2Client) -> list[NetworkInterfaceTypeDef]:
        return ec2.describe_network_interfaces()["NetworkInterfaces"]

    @staticmethod
    def get_load_balancers(
        elb: ElasticLoadBalancingClient,
    ) -> list[LoadBalancerDescriptionTypeDef]:
        return elb.describe_load_balancers()["LoadBalancerDescriptions"]

    @staticmethod
    def get_load_balancer_tags(
        elb: ElasticLoadBalancingClient, lb_name: str
    ) -> list[TagDescriptionTypeDef]:
        return elb.describe_tags(LoadBalancerNames=[lb_name])["TagDescriptions"]

    @staticmethod
    def get_vpc_default_sg_id(vpc_id: str, ec2: EC2Client) -> str | None:
        vpc_security_groups = ec2.describe_security_groups(
            Filters=[
                {"Name": "vpc-id", "Values": [vpc_id]},
                {"Name": "group-name", "Values": ["default"]},
            ]
        )
        # there is only one default
        for sg in vpc_security_groups.get("SecurityGroups", []):
            return sg["GroupId"]

        return None

    @staticmethod
    def get_transit_gateways(ec2: EC2Client) -> list[TransitGatewayTypeDef]:
        tgws = ec2.describe_transit_gateways()
        return tgws.get("TransitGateways", [])

    def get_tgw_default_route_table_id(
        self, ec2: EC2Client, tgw_id: str, tags: Mapping[str, str]
    ) -> str | None:
        tgws = self.get_transit_gateways(ec2)
        tgws = self.filter_on_tags(tgws, tags)
        # we know the party TGW exists, so we can be
        # a little less catious about getting it
        [tgw] = [t for t in tgws if t["TransitGatewayId"] == tgw_id]
        tgw_options = tgw["Options"]
        tgw_has_route_table = tgw_options["DefaultRouteTableAssociation"] == "enable"
        # currently only adding routes
        # to the default route table
        if tgw_has_route_table:
            return tgw_options["AssociationDefaultRouteTableId"]

        return None

    @staticmethod
    def get_transit_gateway_vpc_attachments(
        tgw_id: str, ec2: EC2Client
    ) -> list[TransitGatewayVpcAttachmentTypeDef]:
        atts = ec2.describe_transit_gateway_vpc_attachments(
            Filters=[{"Name": "transit-gateway-id", "Values": [tgw_id]}]
        )
        return atts.get("TransitGatewayVpcAttachments", [])

    def get_tgws_details(
        self,
        account: awsh.Account,
        region_name: str,
        routes_cidr_block: str,
        tags: Mapping,
        route_tables: bool = False,
        security_groups: bool = False,
        route53_associations: bool = False,
    ) -> list[dict[str, Any]]:
        results = []
        ec2 = self._account_ec2_client(account["name"], region_name)
        tgws = ec2.describe_transit_gateways(
            Filters=[{"Name": f"tag:{k}", "Values": [v]} for k, v in tags.items()]
        )
        for tgw in tgws.get("TransitGateways") or []:
            tgw_id = tgw["TransitGatewayId"]
            tgw_arn = tgw["TransitGatewayArn"]
            item: dict[str, str | list[str] | list[dict]] = {
                "tgw_id": tgw_id,
                "tgw_arn": tgw_arn,
                "region": region_name,
            }

            if route53_associations:
                route53 = self._account_route53_client(account["name"], region_name)
                paginator = route53.get_paginator("list_hosted_zones")
                zones = []
                for page in paginator.paginate():
                    for zone in page["HostedZones"]:
                        if zone["Config"]["PrivateZone"]:
                            zone_id = self._get_hosted_zone_id(zone)
                            zones.append(zone_id)
                item["hostedzones"] = zones

            if route_tables or security_groups:
                # both routes and rules are provisioned for resources
                # that are indirectly attached to the TGW.
                # routes are provisioned for route tables that belong
                # to TGWs which are peered to the TGW we are currently
                # handling.
                routes = []
                # rules are provisioned for security groups that belong
                # to VPCs which are attached to the TGW we are currently
                # handling AND to TGWs which are peered to it.
                rules = []
                # this will require to iterate over all reachable TGWs
                attachments = ec2.describe_transit_gateway_peering_attachments(
                    Filters=[{"Name": "transit-gateway-id", "Values": [tgw_id]}]
                )
                for a in attachments.get("TransitGatewayPeeringAttachments") or []:
                    tgw_attachment_id = a["TransitGatewayAttachmentId"]
                    tgw_attachment_state = a["State"]
                    if tgw_attachment_state != "available":
                        continue
                    # we don't care who is who, so let's iterate over parties
                    attachment_parties = [a["RequesterTgwInfo"], a["AccepterTgwInfo"]]
                    for party in attachment_parties:
                        if party["OwnerId"] != account["uid"]:
                            # TGW attachment to another account, skipping
                            continue
                        party_tgw_id = party["TransitGatewayId"]
                        party_region = party["Region"]
                        party_ec2 = self._account_ec2_client(
                            account["name"], party_region
                        )

                        # the TGW route table is automatically populated
                        # with the peered VPC cidr block.
                        # however, to achieve global routing across peered
                        # TGWs in different regions, we need to find all
                        # peering attachments in different regions and collect
                        # the data to later create a route in each peered TGW
                        # in a different region. this will require getting:
                        # - cluster cidr block
                        # - transit gateway attachment id
                        # - transit gateway route table id
                        # we will also pass some additional information:
                        # - transit gateway id
                        # - transit gateway region
                        if route_tables:
                            # don't act on yourself and
                            # routes are propogated within the same region
                            if party_tgw_id != tgw_id and party_region != region_name:
                                party_tgw_route_table_id = (
                                    self.get_tgw_default_route_table_id(
                                        party_ec2, party_tgw_id, tags
                                    )
                                )
                                if party_tgw_route_table_id is not None:
                                    # that's it, we have all
                                    # the information we need
                                    route_item = {
                                        "cidr_block": routes_cidr_block,
                                        "tgw_attachment_id": tgw_attachment_id,
                                        "tgw_id": party_tgw_id,
                                        "tgw_route_table_id": party_tgw_route_table_id,
                                        "region": party_region,
                                    }
                                    routes.append(route_item)

                        # once all the routing is in place, we need to allow
                        # connections in security groups.
                        # in TGW, we need to allow the rules in the VPCs
                        # associated to the TGWs that need to accept the
                        # traffic. we need to collect data about the vpc
                        # attachments for the TGWs, and for each VPC get
                        # the details of it's default securiry group.
                        # this will require getting:
                        # - cluster cidr block
                        # - security group id
                        # we will also pass some additional information:
                        # - vpc id
                        # - vpc region
                        if security_groups:
                            vpc_attachments = self.get_transit_gateway_vpc_attachments(
                                party_tgw_id, party_ec2
                            )
                            for va in vpc_attachments:
                                vpc_attachment_vpc_id = va["VpcId"]
                                vpc_attachment_state = va["State"]
                                if vpc_attachment_state != "available":
                                    continue
                                sg_id = self.get_vpc_default_sg_id(
                                    vpc_attachment_vpc_id, party_ec2
                                )
                                if sg_id is not None:
                                    # that's it, we have all
                                    # the information we need
                                    rule_item = {
                                        "cidr_block": routes_cidr_block,
                                        "security_group_id": sg_id,
                                        "vpc_id": vpc_attachment_vpc_id,
                                        "region": party_region,
                                    }
                                    rules.append(rule_item)

                if route_tables:
                    item["routes"] = routes
                if security_groups:
                    item["rules"] = rules

            results.append(item)

        return results

    @staticmethod
    def _get_vpc_endpoints(
        filters: Sequence[FilterTypeDef], ec2: EC2Client
    ) -> list["VpcEndpointTypeDef"]:
        atts = ec2.describe_vpc_endpoints(Filters=filters)
        return atts.get("VpcEndpoints", [])

    @staticmethod
    def _get_hosted_zone_id(zone: HostedZoneTypeDef) -> str:
        # 'Id': '/hostedzone/THISISTHEZONEID'
        return zone["Id"].split("/")[-1]

    def _get_hosted_zone_record_sets(
        self, route53: Route53Client, zone_name: str
    ) -> list[ResourceRecordSetTypeDef]:
        zones = route53.list_hosted_zones_by_name(DNSName=zone_name)["HostedZones"]
        if not zones:
            return []
        zone_id = self._get_hosted_zone_id(zones[0])
        return route53.list_resource_record_sets(HostedZoneId=zone_id)[  # type: ignore[return-value]
            "ResourceRecordSets"
        ]

    @staticmethod
    def _filter_record_sets(
        record_sets: list[ResourceRecordSetTypeDef], zone_name: str, zone_type: str
    ) -> list[ResourceRecordSetTypeDef]:
        return [
            r
            for r in record_sets
            if r["Name"] == f"{zone_name}." and r["Type"] == zone_type
        ]

    @staticmethod
    def _extract_records(
        resource_records: Iterable[ResourceRecordTypeDef],
    ) -> list[str]:
        # [{'Value': 'ns.example.com.'}, ...]
        return [r["Value"].rstrip(".") for r in resource_records]

    def get_route53_zone_ns_records(
        self, account_name: str, zone_name: str, region: str
    ) -> list[str]:
        route53 = self._account_route53_client(account_name, region)
        record_sets = self._get_hosted_zone_record_sets(route53, zone_name)
        filtered_record_sets = self._filter_record_sets(record_sets, zone_name, "NS")
        if not filtered_record_sets:
            return []
        resource_records = filtered_record_sets[0]["ResourceRecords"]
        ns_records = self._extract_records(resource_records)
        return ns_records

    def get_image_id(
        self, account_name: str, region_name: str, tags: Iterable[AmiTag]
    ) -> str | None:
        """
        Get AMI ID matching the specified criteria.

        :param account_name: the account name to operate on
        :param region_name: aws region name to operate on
        https://docs.aws.amazon.com/cli/latest/reference/ec2/describe-images.html
        """
        ec2 = self._account_ec2_client(account_name, region_name)
        filter_type_defs: list[FilterTypeDef] = [
            {
                "Name": "tag:" + tag.name,
                "Values": [tag.value],
            }
            for tag in tags
        ]
        images = ec2.describe_images(Filters=filter_type_defs)["Images"]
        if len(images) > 1:
            raise ValueError(
                f"found multiple AMI with {tags=} in account {account_name}"
            )
        if not images:
            return None
        return images[0]["ImageId"]

    def describe_rds_db_instance(
        self,
        account_name: str,
        db_instance_name: str,
        region_name: str | None = None,
    ) -> DBInstanceMessageTypeDef:
        """
        Describe a single RDS instance.
        :param account_name: the name of the account in app-interface
        :param db_instance_name: the name of the database (ex. some-database-stage)
        :param region_name: AWS region name for the resource, otherwise fallback to default
        :return: https://docs.aws.amazon.com/AmazonRDS/latest/APIReference/API_DescribeDBInstances.html#API_DescribeDBInstances_ResponseElements
        """
        optional_kwargs = {}

        if region_name:
            optional_kwargs["region_name"] = region_name

        rds = self._account_rds_client(account_name, **optional_kwargs)
        return rds.describe_db_instances(DBInstanceIdentifier=db_instance_name)

    def describe_rds_recommendations(
        self,
        account_name: str,
        region_name: str | None = None,
    ) -> DBRecommendationsMessageTypeDef:
        rds = self._account_rds_client(account_name, region_name)
        return rds.describe_db_recommendations()

    def get_db_valid_upgrade_target(
        self,
        account_name: str,
        engine: str,
        engine_version: str,
        region_name: str | None = None,
    ) -> list[UpgradeTargetTypeDef]:
        """
        Get a list version of the database engine that a DB instance can be upgraded to.
        :param account_name: the name of the account in app-interface
        :param engine: the database engine (ex. mysql, postgres)
        :param engine_version: the database engine version
        :param region_name: AWS region name for the resource, otherwise fallback to default

        :return: https://docs.aws.amazon.com/AmazonRDS/latest/APIReference/API_UpgradeTarget.html
        """
        optional_kwargs = {}

        if region_name:
            optional_kwargs["region_name"] = region_name

        rds = self._account_rds_client(account_name, **optional_kwargs)
        response = rds.describe_db_engine_versions(
            Engine=engine,
            EngineVersion=engine_version,
            IncludeAll=True,
        )

        if versions := response["DBEngineVersions"]:
            return versions[0]["ValidUpgradeTarget"]
        return []

    def check_db_engine_version(
        self,
        account_name: str,
        engine: str,
        engine_version: str,
        region_name: str | None = None,
    ) -> bool:
        """
        Check the version of the database engine is available or deprecated.
        :param account_name: the name of the account in app-interface
        :param engine: the database engine (ex. mysql, postgres)
        :param engine_version: the database engine version
        :param region_name: AWS region name for the resource, otherwise fallback to default
        """
        optional_kwargs = {}

        if region_name:
            optional_kwargs["region_name"] = region_name

        rds = self._account_rds_client(account_name, **optional_kwargs)
        response = rds.describe_db_engine_versions(
            Engine=engine,
            EngineVersion=engine_version,
        )
        return len(response["DBEngineVersions"]) == 1

    def describe_db_parameter_group(
        self,
        account_name: str,
        db_parameter_group_name: str,
        region_name: str | None = None,
    ) -> dict[str, str]:
        optional_kwargs = {}

        if region_name:
            optional_kwargs["region_name"] = region_name

        rds = self._account_rds_client(account_name, **optional_kwargs)
        paginator = rds.get_paginator("describe_db_parameters")
        parameters = {}
        for page in paginator.paginate(DBParameterGroupName=db_parameter_group_name):
            for param in page.get("Parameters", []):
                parameters[param["ParameterName"]] = param.get("ParameterValue", "")
        return parameters

    def get_organization_billing_account(self, account_name: str) -> str:
        org = self._account_organizations_client(account_name)
        return org.describe_organization()["Organization"]["MasterAccountId"]

    def get_s3_object_content(
        self,
        account_name: str,
        bucket_name: str,
        path: str,
        region_name: str | None = None,
    ) -> str:
        s3 = self._account_s3_client(account_name, region_name=region_name)
        return (
            s3.get_object(Bucket=bucket_name, Key=path)["Body"].read().decode("utf-8")
        )

    def list_s3_objects(
        self,
        account_name: str,
        bucket_name: str,
        path: str,
        region_name: str | None = None,
    ) -> list[str]:
        s3 = self._account_s3_client(account_name, region_name=region_name)
        objects = s3.list_objects_v2(Bucket=bucket_name, Prefix=path, Delimiter="/")[
            "Contents"
        ]
        return [
            obj["Key"]
            for obj in sorted(
                objects, key=operator.itemgetter("LastModified"), reverse=True
            )
        ]


def aws_config_file_path() -> str | None:
    config_file_path = os.path.expanduser(
        os.environ.get("AWS_CONFIG_FILE", "~/.aws/config")
    )
    if not os.path.isfile(config_file_path):
        return None
    return config_file_path
