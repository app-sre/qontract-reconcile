# Merge Requests

Module responsible for abstracting a Gitlab Merge Request.

## Creating New MergeRequest Classes

Each type of merge request requires a class that inherits
from reconcile.utils.mr.base.MergeRequestBase.

That class has to comply with the specification below.

### Class Name

The class name is given by the class variable `name`. That name will be
used all around, the most important place being the SQS Message parameter
`pr_type`, used later to create an instance of the same class.

While the name can be anything it is mandatory that it is defined.

### Class Initialization

The `__init__` method has to call `super().__init__()` right after the minimum
parameters initialization. That is required to compose the SQS Message that
will later be used to create a new instance of the same class.

### Class Methods

The minimum methods that have to be defined are:

* `title`: a property that is used to give the Gitlab Merge Request a title.
  It can also be used for building commit messages or as content to committed
  files.
* `description`: a description for the Merge Request.
* `process`: this method is called when submitting the Merge Request to gitlab.
  it's the place for the merge request changes, like creating, updating and
  deleting files. The `process` method is called after the local branch is
  created and right after it the `gitlab_cli.project.mergerequests.create()`
  is called.

### Example

This is an example of a minimum implementation for a new MergeRequest class:

```python
from reconcile.utils.mr.base import MergeRequestBase


class CreateDeleteUser(MergeRequestBase):

    name = 'create_delete_user_mr'

    def __init__(self, username, paths):
        self.username = username
        self.paths = paths

        # Called right after the minimum parameters to recreate
        # an instance with the same data. This is important for
        # building up the SQS message payload.
        super().__init__()

    @property
    def title(self) -> str:
        return f'[{self.name}] delete user {self.username}'

    @property
    def description(self) -> str:
        return f'delete user {self.username}'

    def process(self, gitlab_cli):
        for path in self.paths:
            gitlab_cli.delete_file(branch_name=self.branch,
                                   file_path=path,
                                   commit_message=self.title)
```

## Sending MRs to SQS

To send a Merge Request to SQS, create the corresponding MergeRequest object:

```python
from reconcile.utils.mr import CreateAppInterfaceNotificator


notification = {
    'notification_type': 'Outage',
    'description': 'The AppSRE team is currently investigating an outage',
    'short_description': 'Short Description',
}

merge_request = CreateAppInterfaceNotificator(notification=notification)

```

then create the SQS Client instance:

```python
from reconcile import queries

from reconcile.utils.sqs_gateway import SQSGateway
from reconcile.utils.secret_reader import SecretReader


accounts = queries.get_queue_aws_accounts()
secretReader = SecretReader(queries.get_secret_reader_settings())
sqs_cli = SQSGateway(accounts, secret_reader=secret_reader)
```

and then submit the merge request to the SQS:

```python
merge_request.submit_to_sqs(sqs_cli=sqs_cli)
```

## Sending MRs to Gitlab

To get the message from SQS and use it for sending a Merge Request to gitlab,
first get the SQS messages:


```python
from reconcile import queries

from reconcile.utils.sqs_gateway import SQSGateway
from reconcile.utils.secret_reader import SecretReader


accounts = queries.get_queue_aws_accounts()
settings = queries.get_app_interface_settings()

secretReader = SecretReader(queries.get_secret_reader_settings())
sqs_cli = SQSGateway(accounts, secret_reader=secret_reader)
messages = sqs_cli.receive_messages()
```

then create the Gitlab client instance:

```python
from reconcile.utils.gitlab_api import GitLabApi

instance = queries.get_gitlab_instance()
saas_files = queries.get_saas_files_minimal()
gitlab_cli = GitLabApi(instance, project_id=gitlab_project_id,
                       settings=settings)
```

and then loop the messages, creating the MergeRequest objects and submitting
the merge requests:

```python
from reconcile.utils.mr import init_from_sqs_message

for message in messages:
    receipt_handle, body = message[0], message[1]
    merge_request = init_from_sqs_message(body)
    merge_request.submit_to_gitlab(gitlab_cli=gitlab_cli)
    sqs_cli.delete_message(receipt_handle)
```

## Using the MR Module for Qontract-reconcile Integrations

A given integration might be executed in different environments, like:

* Developer local machine.
* OpenShift cluster outside the VPN.
* OpenShift cluster inside the VPN.
* Jenkins periodic job.

Because we don't want the integrations to care if they are running inside or
outside the VPN, we use the `reconcile.mr_client_gateway.init()` to get the
on of SQS or GitLab client, according to the App Interface settings. Example:

```python
from reconcile import mr_client_gateway
from reconcile.utils.mr import CreateDeleteAwsAccessKey


def run(dry_run, gitlab_project_id):
    ...
    mr = CreateDeleteAwsAccessKey(...)
    with mr_client_gateway.init(gitlab_project_id=gitlab_project_id) as mr_cli:
      mr.submit(cli=mr_cli)
```

If we want to override what's set in App Interface and get a specific client,
say `gitlab`, we would:

```python
from reconcile import mr_client_gateway
from reconcile.utils.mr import CreateDeleteAwsAccessKey


def run(dry_run, gitlab_project_id):
    ...
    mr = CreateDeleteAwsAccessKey(...)
    with mr_client_gateway.init(sqs_or_gitlab='gitlab',
                           gitlab_project_id=gitlab_project_id) as mr_cli:
      mr.submit(cli=mr_cli)
```
