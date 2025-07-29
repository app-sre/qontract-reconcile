# Client Factories and Managers

To ensure that interactions with external services are consistent, secure, and efficient, `qontract-reconcile` uses a pattern of centralized client factories and managers. Instead of each integration instantiating its own API client, it requests a pre-configured client from a shared utility.

This pattern abstracts away the complexities of authentication, session management, and endpoint configuration.

## Key Examples

### `OC_Map` for OpenShift Clients

The most prominent example is the `OC_Map` class (`reconcile.utils.oc.OC_Map`), which manages connections to multiple OpenShift clusters.

An integration that needs to talk to OpenShift clusters doesn't build its own client. Instead, it's typically provided with an `OC_Map` instance that is pre-populated with authenticated clients for all the clusters it needs to touch.

**How it's used:**

```python
# In openshift_base.py, a map of clients is created
oc_map = OC_Map(
    clusters=clusters_info,
    integration=QONTRACT_INTEGRATION,
    thread_pool_size=thread_pool_size,
    # ... other settings ...
)

# An integration can then retrieve a client for a specific cluster
oc_client = oc_map.get(cluster_name)

# And use it to interact with the cluster API
if oc_client.is_cluster_admin():
    # ... perform admin actions
```

The `OC_Map` handles:
- Reading the cluster connection details and credentials from `app-interface`.
- Authenticating with each cluster.
- Managing jump host connections for private clusters.
- Caching clients to avoid repeated authentication.

### `AWSApi` for AWS Clients

Similarly, the `reconcile.utils.aws_api.AWSApi` class provides a standardized way to get `boto3` clients for interacting with AWS.

```python
from reconcile.utils.aws_api import AWSApi

# The AWSApi object manages STS sessions for multiple accounts
aws_api = AWSApi(thread_pool_size)

# Get a boto3 session for a specific account and region
session = aws_api.get_session(account_name, region)

# Get a low-level client from the session
s3_client = session.client('s3')
```

### `github_api` for GitHub Clients

The `reconcile.utils.github_api.get_github_api()` function returns a memoized `Github` API object, ensuring that only one connection is made per GitHub instance.

## Benefits of the Pattern

- **Consistency**: All integrations use the same configuration and authentication logic.
- **Security**: Credential handling is centralized and not left to individual integrations.
- **Efficiency**: Clients and sessions are cached and reused, improving performance.
- **Simplicity**: Integration developers can focus on their reconciliation logic instead of boilerplate client setup.
