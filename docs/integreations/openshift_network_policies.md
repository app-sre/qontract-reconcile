# Enable network traffic between Namespaces via App-Interface (`/openshift/namespace-1.yml`)

To enable network traffic between namespaces, a user must add the following to a namespace declaration:

```yaml
networkPoliciesAllow:
- $ref: /path/to/source-namespace.yml
```

This will allow traffic from the `source-namespace` to the namespace in which this section is defined.
