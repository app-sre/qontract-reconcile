"""Tests for reconcile.openshift_bindings.models module."""

from pytest_mock import MockerFixture

from reconcile.gql_definitions.common.app_interface_clusterrole import (
    AccessV1 as ClusterAccessV1,
)
from reconcile.gql_definitions.common.app_interface_clusterrole import (
    BotV1 as ClusterBotV1,
)
from reconcile.gql_definitions.common.app_interface_clusterrole import (
    ClusterV1 as ClusterRoleClusterV1,
)
from reconcile.gql_definitions.common.app_interface_clusterrole import (
    RoleV1 as ClusterRoleV1,
)
from reconcile.gql_definitions.common.app_interface_clusterrole import (
    UserV1 as ClusterUserV1,
)
from reconcile.gql_definitions.common.app_interface_roles import (
    AccessV1,
    BotV1,
    NamespaceV1,
    RoleV1,
    UserV1,
)
from reconcile.openshift_bindings.models import (
    ClusterRoleBindingSpec,
    RoleBindingSpec,
    ServiceAccountSpec,
    get_usernames_from_users,
)
from reconcile.openshift_bindings.utils import is_valid_namespace


class TestIsValidNamespace:
    """Tests for is_valid_namespace function."""

    def test_valid_namespace(
        self, mocker: MockerFixture, test_namespace: NamespaceV1
    ) -> None:
        """Namespace with managed_roles=True, in shard, not deleted is valid."""
        mocker.patch(
            "reconcile.openshift_bindings.utils.is_in_shard", return_value=True
        )
        mocker.patch(
            "reconcile.openshift_bindings.utils.ob.is_namespace_deleted",
            return_value=False,
        )
        assert is_valid_namespace(test_namespace) is True

    def test_invalid_namespace_no_managed_roles(
        self, mocker: MockerFixture, test_namespace_no_managed_roles: NamespaceV1
    ) -> None:
        """Namespace without managed_roles is invalid."""
        mocker.patch(
            "reconcile.openshift_bindings.utils.is_in_shard", return_value=True
        )
        mocker.patch(
            "reconcile.openshift_bindings.utils.ob.is_namespace_deleted",
            return_value=False,
        )
        assert is_valid_namespace(test_namespace_no_managed_roles) is False

    def test_invalid_namespace_not_in_shard(
        self, mocker: MockerFixture, test_namespace: NamespaceV1
    ) -> None:
        """Namespace not in shard is invalid."""
        mocker.patch(
            "reconcile.openshift_bindings.utils.is_in_shard", return_value=False
        )
        mocker.patch(
            "reconcile.openshift_bindings.utils.ob.is_namespace_deleted",
            return_value=False,
        )
        assert is_valid_namespace(test_namespace) is False

    def test_invalid_namespace_deleted(
        self, mocker: MockerFixture, test_namespace: NamespaceV1
    ) -> None:
        """Deleted namespace is invalid."""
        mocker.patch(
            "reconcile.openshift_bindings.utils.is_in_shard", return_value=True
        )
        mocker.patch(
            "reconcile.openshift_bindings.utils.ob.is_namespace_deleted",
            return_value=True,
        )
        assert is_valid_namespace(test_namespace) is False


class TestServiceAccountSpec:
    """Tests for ServiceAccountSpec dataclass."""

    def test_from_bots_valid(self, test_bot: BotV1) -> None:
        """Valid bot creates ServiceAccountSpec."""
        specs = ServiceAccountSpec.from_bots([test_bot])
        assert len(specs) == 1
        assert specs[0].sa_namespace_name == "test-namespace"
        assert specs[0].sa_name == "test-sa"

    def test_from_bots_multiple(self, test_bot: BotV1) -> None:
        """Multiple bots create multiple ServiceAccountSpecs."""
        bot2 = BotV1(openshift_serviceaccount="other-ns/other-sa")
        specs = ServiceAccountSpec.from_bots([test_bot, bot2])
        assert len(specs) == 2

    def test_from_bots_none(self) -> None:
        """None bots returns empty list."""
        specs = ServiceAccountSpec.from_bots(None)
        assert specs == []

    def test_from_bots_empty_list(self) -> None:
        """Empty bot list returns empty spec list."""
        specs = ServiceAccountSpec.from_bots([])
        assert specs == []

    def test_from_bots_no_sa(self, test_bot_no_sa: BotV1) -> None:
        """Bot without service account is skipped."""
        specs = ServiceAccountSpec.from_bots([test_bot_no_sa])
        assert specs == []

    def test_from_bots_invalid_format(self, test_bot_invalid_sa: BotV1) -> None:
        """Bot with invalid SA format (no slash) is skipped."""
        specs = ServiceAccountSpec.from_bots([test_bot_invalid_sa])
        assert specs == []

    def test_from_bots_cluster_bot(self, test_cluster_bot: ClusterBotV1) -> None:
        """ClusterBotV1 type also works."""
        specs = ServiceAccountSpec.from_bots([test_cluster_bot])
        assert len(specs) == 1
        assert specs[0].sa_namespace_name == "cluster-ns"
        assert specs[0].sa_name == "cluster-sa"


class TestGetUsernamesFromUsers:
    """Tests for get_usernames_from_users function."""

    def test_get_usernames_from_users_single_key(self, test_user: UserV1) -> None:
        """Extract usernames with single key."""
        usernames = get_usernames_from_users([test_user], user_keys=["org_username"])
        assert usernames == {"test-org-user"}

    def test_get_usernames_from_users_multiple_keys(self, test_user: UserV1) -> None:
        """Extract usernames with multiple keys returns all matches."""
        usernames = get_usernames_from_users(
            [test_user], user_keys=["org_username", "github_username"]
        )
        assert usernames == {"test-org-user", "test-github-user"}

    def test_get_usernames_from_users_multiple_users(
        self, test_user: UserV1, test_user_2: UserV1
    ) -> None:
        """Extract usernames from multiple users."""
        usernames = get_usernames_from_users(
            [test_user, test_user_2], user_keys=["org_username"]
        )
        assert usernames == {"test-org-user", "test-org-user-2"}

    def test_get_usernames_from_users_none_users(self) -> None:
        """None users returns empty set."""
        usernames = get_usernames_from_users(None, user_keys=["org_username"])
        assert usernames == set()

    def test_get_usernames_from_users_none_keys(self, test_user: UserV1) -> None:
        """None user_keys returns empty set."""
        usernames = get_usernames_from_users([test_user], user_keys=None)
        assert usernames == set()

    def test_get_usernames_from_users_invalid_key(self, test_user: UserV1) -> None:
        """Invalid key is skipped."""
        usernames = get_usernames_from_users([test_user], user_keys=["invalid_key"])
        assert usernames == set()

    def test_get_usernames_from_users_cluster_users(
        self, test_cluster_user: ClusterUserV1
    ) -> None:
        """ClusterUserV1 type also works."""
        usernames = get_usernames_from_users(
            [test_cluster_user], user_keys=["org_username"]
        )
        assert usernames == {"test-cluster-user"}


class TestRoleBindingSpec:
    """Tests for RoleBindingSpec class."""

    def test_create_role_binding_spec_with_role(
        self,
        mocker: MockerFixture,
        test_access_with_role: AccessV1,
        test_user: UserV1,
        test_bot: BotV1,
    ) -> None:
        """Create RoleBindingSpec with namespace-scoped role."""
        mocker.patch(
            "reconcile.openshift_bindings.models.ob.determine_user_keys_for_access",
            return_value=["org_username"],
        )

        spec = RoleBindingSpec.create_role_binding_spec(
            access=test_access_with_role,
            users=[test_user],
            enforced_user_keys=None,
            bots=[test_bot],
            support_role_ref=True,
        )

        assert spec is not None
        assert spec.role_name == "test-role"
        assert spec.role_kind == "Role"  # support_role_ref=True
        assert spec.resource_kind == "RoleBinding"
        assert spec.namespace.name == "test-namespace"
        assert spec.usernames == {"test-org-user"}
        assert len(spec.openshift_service_accounts) == 1

    def test_create_role_binding_spec_with_cluster_role(
        self,
        mocker: MockerFixture,
        test_access_with_cluster_role: AccessV1,
        test_user: UserV1,
    ) -> None:
        """Create RoleBindingSpec with cluster role reference."""
        mocker.patch(
            "reconcile.openshift_bindings.models.ob.determine_user_keys_for_access",
            return_value=["org_username"],
        )

        spec = RoleBindingSpec.create_role_binding_spec(
            access=test_access_with_cluster_role,
            users=[test_user],
            support_role_ref=False,
        )

        assert spec is not None
        assert spec.role_name == "test-cluster-role"
        assert spec.role_kind == "ClusterRole"

    def test_create_role_binding_spec_no_namespace(
        self, mocker: MockerFixture, test_user: UserV1
    ) -> None:
        """Returns None when access has no namespace."""
        access = AccessV1(namespace=None, role="test-role", clusterRole=None)

        spec = RoleBindingSpec.create_role_binding_spec(
            access=access,
            users=[test_user],
        )

        assert spec is None

    def test_create_role_binding_spec_no_role(
        self, mocker: MockerFixture, test_access_no_role: AccessV1, test_user: UserV1
    ) -> None:
        """Returns None when access has no role or cluster role."""
        spec = RoleBindingSpec.create_role_binding_spec(
            access=test_access_no_role,
            users=[test_user],
        )

        assert spec is None

    def test_create_rb_specs_from_role(
        self, mocker: MockerFixture, test_role: RoleV1
    ) -> None:
        """Create RoleBindingSpecs from role configuration."""
        mocker.patch(
            "reconcile.openshift_bindings.models.is_valid_namespace", return_value=True
        )
        mocker.patch(
            "reconcile.openshift_bindings.models.ob.determine_user_keys_for_access",
            return_value=["org_username"],
        )

        specs = RoleBindingSpec.create_rb_specs_from_role(test_role)

        assert len(specs) == 1
        assert specs[0].role_name == "test-role"

    def test_create_rb_specs_from_role_invalid_namespace(
        self, mocker: MockerFixture, test_role: RoleV1
    ) -> None:
        """Skip invalid namespaces when creating RoleBindingSpecs."""
        mocker.patch(
            "reconcile.openshift_bindings.models.is_valid_namespace", return_value=False
        )

        specs = RoleBindingSpec.create_rb_specs_from_role(test_role)

        assert specs == []

    def test_construct_user_oc_resource(
        self, mocker: MockerFixture, test_access_with_role: AccessV1, test_user: UserV1
    ) -> None:
        """Construct OpenShift resource for user."""
        mocker.patch(
            "reconcile.openshift_bindings.models.ob.determine_user_keys_for_access",
            return_value=["org_username"],
        )

        spec = RoleBindingSpec.create_role_binding_spec(
            access=test_access_with_role,
            users=[test_user],
        )

        assert spec is not None
        resource = spec.construct_user_oc_resource("test-org-user")

        assert resource.name == "test-role-test-org-user"
        assert resource.body["kind"] == "RoleBinding"
        assert resource.body["apiVersion"] == "rbac.authorization.k8s.io/v1"
        assert resource.body["roleRef"]["name"] == "test-role"
        assert resource.body["subjects"][0]["kind"] == "User"
        assert resource.body["subjects"][0]["name"] == "test-org-user"

    def test_construct_sa_oc_resource(
        self, mocker: MockerFixture, test_access_with_role: AccessV1, test_user: UserV1
    ) -> None:
        """Construct OpenShift resource for service account."""
        mocker.patch(
            "reconcile.openshift_bindings.models.ob.determine_user_keys_for_access",
            return_value=["org_username"],
        )

        spec = RoleBindingSpec.create_role_binding_spec(
            access=test_access_with_role,
            users=[test_user],
        )

        assert spec is not None
        resource = spec.construct_sa_oc_resource("test-ns", "test-sa")

        assert resource.name == "test-role-test-ns-test-sa"
        assert resource.body["subjects"][0]["kind"] == "ServiceAccount"
        assert resource.body["subjects"][0]["name"] == "test-sa"
        assert resource.body["subjects"][0]["namespace"] == "test-ns"

    def test_get_oc_resources(
        self,
        mocker: MockerFixture,
        test_access_with_role: AccessV1,
        test_user: UserV1,
        test_bot: BotV1,
    ) -> None:
        """Get all OC resources (users + service accounts)."""
        mocker.patch(
            "reconcile.openshift_bindings.models.ob.determine_user_keys_for_access",
            return_value=["org_username"],
        )

        spec = RoleBindingSpec.create_role_binding_spec(
            access=test_access_with_role,
            users=[test_user],
            bots=[test_bot],
        )

        assert spec is not None
        resources = spec.get_oc_resources()

        # 1 user + 1 service account
        assert len(resources) == 2


class TestClusterRoleBindingSpec:
    """Tests for ClusterRoleBindingSpec class."""

    def test_create_cluster_role_binding_specs(
        self, mocker: MockerFixture, test_cluster_role: ClusterRoleV1
    ) -> None:
        """Create ClusterRoleBindingSpecs from cluster role."""
        mocker.patch(
            "reconcile.openshift_bindings.models.ob.determine_user_keys_for_access",
            return_value=["org_username"],
        )

        specs = ClusterRoleBindingSpec.create_cluster_role_binding_specs(
            test_cluster_role
        )

        assert len(specs) == 1
        assert specs[0].role_name == "test-cluster-role"
        assert specs[0].role_kind == "ClusterRole"
        assert specs[0].resource_kind == "ClusterRoleBinding"

    def test_create_cluster_role_binding_specs_no_cluster(
        self, mocker: MockerFixture
    ) -> None:
        """Skip access without cluster."""
        cluster_role = ClusterRoleV1(
            name="test-role",
            users=[],
            bots=[],
            access=[ClusterAccessV1(cluster=None, clusterRole="test-role")],
            expirationDate=None,
        )

        specs = ClusterRoleBindingSpec.create_cluster_role_binding_specs(cluster_role)

        assert specs == []

    def test_create_cluster_role_binding_specs_no_role(
        self, mocker: MockerFixture, test_cluster_role_cluster: ClusterRoleClusterV1
    ) -> None:
        """Skip access without cluster role."""
        cluster_role = ClusterRoleV1(
            name="test-role",
            users=[],
            bots=[],
            access=[
                ClusterAccessV1(cluster=test_cluster_role_cluster, clusterRole=None)
            ],
            expirationDate=None,
        )

        specs = ClusterRoleBindingSpec.create_cluster_role_binding_specs(cluster_role)

        assert specs == []

    def test_get_user_keys(
        self, mocker: MockerFixture, test_cluster_role_cluster: ClusterRoleClusterV1
    ) -> None:
        """Get user keys from cluster auth configuration."""
        mock_determine = mocker.patch(
            "reconcile.openshift_bindings.models.ob.determine_user_keys_for_access",
            return_value=["org_username"],
        )

        user_keys = ClusterRoleBindingSpec.get_user_keys(test_cluster_role_cluster)

        assert user_keys == ["org_username"]
        mock_determine.assert_called_once()
