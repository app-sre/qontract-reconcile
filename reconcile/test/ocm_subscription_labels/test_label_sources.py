from reconcile.ocm_subscription_labels.integration import ClusterSubscriptionLabelSource
from reconcile.ocm_subscription_labels.label_sources import LabelOwnerRef


def test_cluster_subscription_label_source_managed_label_discovery(
    cluster_file_subscription_label_source: ClusterSubscriptionLabelSource,
) -> None:
    """
    Test that the init method for ClusterSubscriptionLabelSource properly
    discovers the managed label prefixes from the clusters based on the parent
    label prefix.
    """
    assert cluster_file_subscription_label_source.managed_label_prefixes() == {
        "my-label-prefix.to-be-added",
        "my-label-prefix.to-be-changed",
    }


def test_cluster_subscription_label_source_get_labels(
    cluster_file_subscription_label_source: ClusterSubscriptionLabelSource,
    subscription_label_desired_state: dict[LabelOwnerRef, dict[str, str]],
) -> None:
    assert (
        cluster_file_subscription_label_source.get_labels()
        == subscription_label_desired_state
    )
