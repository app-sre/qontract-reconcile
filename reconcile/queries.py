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
    path
    name
    automationToken {
      path
      field
    }
    deleteKeys
  }
}
"""

NAMESPACES_QUERY = """
{
  namespaces: namespaces_v1 {
    name
    cluster {
      name
      serverUrl
      jumpHost {
          hostname
          knownHosts
          user
          port
          identity {
              path
              field
              format
          }
      }
      automationToken {
        path
        field
        format
      }
      disable {
        integrations
      }
    }
    openshiftAcme {
      name
      image
      overrides {
        deploymentName
        roleName
        rolebindingName
        serviceaccountName
      }
    }
  }
}
"""
