GITLAB_INSTANCES_QUERY = """
{
  instances: gitlabinstance_v1 {
    url
    token {
      path
      field
    }
    managedGroups
    sslVerify
  }
}
"""

AWS_ACCOUNTS_QUERY = """
{
  accounts: awsaccounts_v1 {
    name
    automationToken {
      path
      field
    }
  }
}
"""
