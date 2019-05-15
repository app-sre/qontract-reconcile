from utils.jump_host import (JumpHostSSHRestApi,
                             DummySSHServer,
                             HTTPStatusCodeError)


class OpenshiftRestApi(object):
    """A class to simply Openshift API"""

    DEFAULT_CONNECT_TIMEOUT = 5
    DEFAULT_READ_TIMEOUT = 15

    def __init__(self,
                 host='https://127.0.0.1',
                 headers=None,
                 verify_ssl=True,
                 jump_host=None):

        self.api_host = host
        self.headers = headers
        self.verify_ssl = verify_ssl

        if jump_host is None:
            ssh_server = DummySSHServer()
        else:
            ssh_server = JumpHostSSHRestApi(jump_host)

        self.set_ssh_server(ssh_server)

    def cleanup(self):
        self.get_ssh_server().cleanup()

    def get(self, api_path, **kwargs):
        return self.req('get', api_path, **kwargs)

    def post(self, api_path, **kwargs):
        return self.req('post', api_path, **kwargs)

    def put(self, api_path, **kwargs):
        return self.req('put', api_path, **kwargs)

    def delete(self, api_path, **kwargs):
        return self.req('delete', api_path, **kwargs)

    def req(self, method_name, api_path, **kwargs):
        """Do API query, return requested type"""

        if self.api_host.endswith('/') and api_path.startswith('/'):
            api_path = api_path[1:]

        if not kwargs.get('timeout'):
            timeout = (self.DEFAULT_CONNECT_TIMEOUT, self.DEFAULT_READ_TIMEOUT)
            kwargs['timeout'] = timeout

        if not kwargs.get('verify'):
            kwargs['verify'] = self.verify_ssl

        if not kwargs.get('headers'):
            kwargs['headers'] = self.headers.copy()

        else:
            headers = self.headers.copy()
            headers.update(kwargs['headers'])
            kwargs['headers'] = headers

        with self.get_ssh_server() as server:
            method = getattr(server, method_name)
            response = method(self.api_host + api_path, **kwargs)
            self.raise_for_status(response)

        return response.json()

    def get_ssh_server(self):
        return self.ssh_server

    def set_ssh_server(self, server):
        self.ssh_server = server

    def raise_for_status(self, response):
        if response.status_code not in [200, 201, 204]:
            raise HTTPStatusCodeError(response.status_code)


class Openshift(object):
    """Wrapper around OpenShift API calls"""

    ora = None
    namespace = None

    def __init__(self, openshift_api_url='', openshift_api_token='',
                 verify_ssl=True, jump_host=None):

        headers = {'Authorization': 'Bearer ' + openshift_api_token}
        self.ora = OpenshiftRestApi(
            host=openshift_api_url, headers=headers,
            verify_ssl=verify_ssl, jump_host=jump_host)

    def __oapi_get(self, api_path, **kwargs):
        res = self.ora.get(api_path, **kwargs)
        return res

    def __oapi_post(self, api_path, **kwargs):
        res = self.ora.post(api_path, **kwargs)
        return res

    def __oapi_put(self, api_path, **kwargs):
        res = self.ora.put(api_path, **kwargs)
        return res

    def __oapi_delete(self, api_path, **kwargs):
        res = self.ora.delete(api_path, **kwargs)
        return res

    def cleanup(self):
        self.ora.cleanup()

    def get_version(self):
        """Get cluster version"""

        uri = '/oapi/v1'
        return self.__oapi_get(uri)

    def get_user(self, username="~"):
        """Get logged in user details

        Default to currently logged in user
        """

        uri = '/apis/user.openshift.io/v1/users/' + username
        return self.__oapi_get(uri)

    def delete_user(self, username):
        """Delete a user"""

        uri = '/apis/user.openshift.io/v1/users/' + username
        res = self.__oapi_delete(uri)
        return res

    def delete_identity(self, identity):
        """Delete an identity"""

        uri = '/apis/user.openshift.io/v1/identities/' + identity
        res = self.__oapi_delete(uri)
        return res

    def get_users(self):
        """Get logged in user details

        Default to currently logged in user
        """

        uri = '/apis/user.openshift.io/v1/users'
        return self.__oapi_get(uri)

    def get_project(self, projectname):
        """Get list of projects"""

        uri = '/oapi/v1/projects/' + projectname
        return self.__oapi_get(uri)

    def get_projects(self):
        """Get list of projects"""

        uri = '/oapi/v1/projects'
        res = self.__oapi_get(uri)
        return res.get('items', [])

    def get_pods(self, namespace=None, labelSelector=None):
        """Get pods details"""

        if namespace:
            uri = '/api/v1/namespaces/' + namespace + '/pods'
        else:
            uri = '/api/v1/pods'

        params = None
        if labelSelector:
            params = {'labelSelector': labelSelector}

        res = self.__oapi_get(uri, params=params)
        return res.get('items', [])

    def get_buildconfigs(self, namespace):
        """Get buildconfigs for a namespace"""

        uri = '/oapi/v1/namespaces/' + namespace + '/buildconfigs'
        res = self.__oapi_get(uri)
        return res.get('items', [])

    def get_builds(self, namespace):
        """Get builds for a namespace"""

        uri = '/oapi/v1/namespaces/' + namespace + '/builds'
        res = self.__oapi_get(uri)
        return res.get('items', [])

    def get_configmaps(self, namespace):
        """Get configmaps for a namespace"""

        uri = '/api/v1/namespaces/' + namespace + '/configmaps'
        res = self.__oapi_get(uri)
        return res.get('items', [])

    def get_secrets(self, namespace):
        """Get secrets for a namespace"""

        uri = '/api/v1/namespaces/' + namespace + '/secrets'
        res = self.__oapi_get(uri)
        return res.get('items', [])

    def get_deploymentconfig(self, namespace, dcname):
        """Get a single deploymentconfig details"""

        uri = '/oapi/v1/namespaces/{}/deploymentconfigs/{}'.format(
            namespace, dcname
        )

        return self.__oapi_get(uri)

    def get_deploymentconfigs(self, namespace):
        """Get deploymentconfigs details"""

        uri = '/oapi/v1/namespaces/' + namespace + '/deploymentconfigs'
        res = self.__oapi_get(uri)
        return res.get('items', [])

    def get_quota(self, namespace, qtype=None):
        """Get specific ResourceQuota details"""

        uri = '/api/v1/namespaces/' + namespace + '/resourcequotas'

        if qtype:
            uri = uri + '/' + qtype

        res = self.__oapi_get(uri)

        if 'items' in res:
            return res['items']

        return res['status']

    def get_quotas(self, namespace):
        """Get ResourceQuotas details"""

        uri = '/api/v1/namespaces/' + namespace + '/resourcequotas'
        res = self.__oapi_get(uri)
        return res.get('items', [])

    def get_services(self, namespace):
        """Get services details"""

        uri = '/api/v1/namespaces/' + namespace + '/services'
        res = self.__oapi_get(uri)
        return res.get('items', [])

    def get_routes(self, namespace):
        """Get status of routes"""

        uri = '/oapi/v1/namespaces/' + namespace + '/routes'
        res = self.__oapi_get(uri)
        return res.get('items', [])

    def get_rolebindings(self, namespace, role=None):
        """
        Get rolebindings for a namespace

        If role is supplied it will filter by role
        """

        uri = '/apis/authorization.openshift.io/v1/namespaces/' + \
            namespace + '/rolebindings'

        res = self.__oapi_get(uri)
        items = res['items']

        if role:
            items = [r for r in items if r[u'roleRef'][u'name'] == role]

        return items

    def remove_role_from_user(self, namespace, role, user, kind):
        """
        Remove a user from a role

        This method finds the roleBinding that grants that permissions and
        either removes the roleBinding entirely (if the user is the only
        subject in the roleBinding) or it updates the roleBinding to remove
        the user from the roleBinding
        """

        # fetch all roleBindings in the ns for that specific role
        rbs = self.get_rolebindings(namespace, role)

        # find the roleBinding for the user
        rb = None
        subject = None
        userName = None
        for r in rbs:
            for s in r[u'subjects']:
                if s[u'kind'] != kind:
                    continue

                if s[u'kind'] == 'User' and s[u'name'] == user:
                    rb = r
                    subject = s
                    userName = user
                    break
                elif s[u'kind'] == 'ServiceAccount' and \
                        s[u'name'] == user.split('/')[1] and \
                        s[u'namespace'] == user.split('/')[0]:
                    rb = r
                    subject = s
                    userName = "system:serviceaccount:" + \
                        user.split('/')[0] + ":" + user.split('/')[1]
                    break

        if rb is None:
            raise Exception(
                "Could not find roleBinding for ns: '%s', role: '%s', "
                "user: '%s'" % (namespace, role, user))

        uri = "/apis/authorization.openshift.io/v1/namespaces/" + \
            namespace + "/rolebindings/" + rb['metadata']['name']

        if len(rb[u'subjects']) == 1:
            # if user is the only subject in the roleBinding, we can just
            # remove the rb
            return self.__oapi_delete(uri)
        else:
            # remove the user from 'subjects' and 'userNames' and then update
            # (PUT) the roleBinding.
            rb[u'subjects'].remove(subject)
            rb[u'userNames'].remove(userName)

            return self.__oapi_put(uri, json=rb)

    def add_role_to_user(self, namespace, role, user, kind):
        """
        Add role to user

        Creates a rolebinding that grants the requested role to the user. It
        will be a rolebinding with a single subject in it.
        """

        # fetch all roleBindings in the ns for that specific role
        rbs = self.get_rolebindings(namespace, role)

        # calculate the name of the rolebinding
        rb_names = [rb[u'metadata'][u'name'] for rb in rbs]
        if role not in rb_names:
            rb_name = role
        else:
            i = 0
            while True:
                temp_rb_name = u"%s-%s" % (role, i)
                if temp_rb_name not in rb_names:
                    rb_name = temp_rb_name
                    break
                else:
                    i += 1

        uri = "/apis/authorization.openshift.io/v1/namespaces/" + \
            namespace + "/rolebindings"

        if kind == 'User':
            subject_namespace = u''
            name = user
            userName = user
        if kind == 'ServiceAccount':
            subject_namespace = user.split('/')[0]
            name = user.split('/')[1]
            userName = "system:serviceaccount:" + \
                subject_namespace + ":" + name

        rb = {u'groupNames': None,
              u'metadata': {u'name': rb_name, u'namespace': namespace},
              u'roleRef': {u'name': role},
              u'subjects': [{u'kind': kind, u'namespace': subject_namespace,
                             u'name': name}],
              u'userNames': [userName]}

        return self.__oapi_post(uri, json=rb)

    def get_pvs(self):
        """Get persistentvolumes"""

        uri = '/api/v1/persistentvolumes'
        res = self.__oapi_get(uri)
        return res.get('items', [])

    def get_pvcs(self, namespace=None):
        """Get persistentvolumeclaims"""

        if namespace:
            uri = '/api/v1/namespaces/' + namespace + '/persistentvolumeclaims'
        else:
            uri = '/api/v1/persistentvolumeclaims'

        res = self.__oapi_get(uri)
        return res.get('items', [])

    def get_storageclasses(self):
        """Get storageclasses"""

        uri = '/apis/storage.k8s.io/v1/storageclasses'
        res = self.__oapi_get(uri)
        return res.get('items', None)

    def get_nodes(self):
        """Get openshift cluster nodes"""

        uri = '/api/v1/nodes'
        res = self.__oapi_get(uri)
        return res.get('items', [])
