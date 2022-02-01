# Manage OpenShift Groups association via App-Interface (`/openshift/cluster-1.yml`)

Groups should be defined under the `managedGroups` section in a cluster file. This is a list of group names that are managed. To associate a user to a group, the user has to be associated to a role that has `access` to the OpenShift group:

```yaml
access:
- cluster:
    $ref: /path/to/cluster.yml
  group: <groupName>
```

Notes:
* The `dedicated-admins` group is managed via OCM using the [ocm-groups](/reconcile/ocm_groups.py) integration, whereas all other groups are managed via OC using the [openshift-groups](/reconcile/openshift_groups.py) integration.
