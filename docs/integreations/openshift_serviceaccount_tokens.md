# Self-Service OpenShift ServiceAccount tokens via App-Interface (`/openshift/namespace-1.yml`)

To add a Secret to a namespace, containing the token of a ServiceAccount from another namespace, a user must add the following to a namespace declaration:

```yaml
openshiftServiceAccountTokens:
- namespace:
    $ref: /path/to/<namespace>.yml
  serviceAccountName: <serviceAccountName>
  name: <name of the output resource to be created> # optional
```

The integration will get the token belonging to that ServiceAccount and add it into a Secret called:
`<clusterName>-<namespaceName>-<ServiceAccountName>`. This is the default name unless `name` is defined.
The Secret will have a single key called `token`, containing a token of that ServiceAccount.

Notes:
The integration can also output all tokens to Vault by using the `--vault-output-path` argument.
