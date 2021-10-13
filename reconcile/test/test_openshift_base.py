import copy

from reconcile.openshift_base import remove_clusters_empty_server_url


def test_remove_clusters_empty_server_url_no_removal():
    initial_clusters = [
        {'name': 'cluster-1', 'serverUrl': 'http://localhost'},
        {'name': 'cluster-2', 'serverUrl': 'http://localhost'}
    ]

    clusters = copy.deepcopy(initial_clusters)

    remove_clusters_empty_server_url(clusters)

    assert clusters == initial_clusters


def test_remove_cluster_empty_server_url_removal():
    clusters = [
        {'name': 'cluster-1', 'serverUrl': 'http://localhost'},
        {'name': 'cluster-2', 'serverUrl': ''}
    ]

    remove_clusters_empty_server_url(clusters)

    assert clusters == [
        {'name': 'cluster-1', 'serverUrl': 'http://localhost'}
    ]
