from reconcile.utils.ocm.base import (
    OCMAWSSTS,
    OCMClusterAWSOperatorRole,
    OCMClusterAWSSettings,
)


def build_aws_settings(
    account_role_prefix: str, operator_role_prefix: str
) -> OCMClusterAWSSettings:
    account_role_arn_base = f"arn:aws:iam::123456789012:role/{account_role_prefix}"
    operator_role_arn_base = f"arn:aws:iam::123456789012:role/{operator_role_prefix}"
    return OCMClusterAWSSettings(
        sts=OCMAWSSTS(
            enabled=True,
            role_arn=f"{account_role_arn_base}-Installer-Role",
            support_role_arn=f"{account_role_arn_base}-Support-Role",
            instance_iam_roles={
                "master_role_arn": f"{account_role_arn_base}-ControlPlane-Role",
                "worker_role_arn": f"{account_role_arn_base}-Worker-Role",
            },
            oidc_endpoint_url="https://rh-oidc.s3.us-east-1.amazonaws.com/12345",
            operator_role_prefix="openshift",
            operator_iam_roles=[
                OCMClusterAWSOperatorRole(
                    id="",
                    name="cloud-credentials",
                    namespace="openshift-cloud-credential-operator",
                    role_arn=f"{operator_role_arn_base}o-penshift-cloud-network-config-co",
                    service_account="",
                ),
                OCMClusterAWSOperatorRole(
                    id="",
                    name="ebs-cloud-credentials",
                    namespace="openshift-cluster-csi-drivers",
                    role_arn=f"{operator_role_arn_base}-openshift-cluster-csi-drivers-ebs",
                    service_account="",
                ),
            ],
        )
    )


def test_ocm_cluster_aws_settings_account_roles() -> None:
    aws_settings = build_aws_settings("ManagedOpenshift", "my-cluster-abc")
    assert len(aws_settings.account_roles) == 4


def test_ocm_cluster_aws_settings_account_roles_no_sts() -> None:
    aws_settings = OCMClusterAWSSettings(sts=None)
    assert aws_settings.account_roles == []


def test_ocm_cluster_aws_settings_account_roles_sts_disabled() -> None:
    aws_settings = OCMClusterAWSSettings(sts=OCMAWSSTS(enabled=False))
    assert aws_settings.account_roles == []


def test_ocm_cluster_aws_settings_account_role_prefix() -> None:
    aws_settings = build_aws_settings("ManagedOpenshift", "my-cluster-abc")
    assert aws_settings.account_role_prefix == "ManagedOpenshift"


def test_ocm_cluster_aws_settings_account_role_prefix_none() -> None:
    aws_settings = build_aws_settings("ManagedOpenshift", "my-cluster-abc")
    assert aws_settings.sts
    aws_settings.sts.role_arn = None
    assert aws_settings.account_role_prefix is None
