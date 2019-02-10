# ldap requires `yum install openldap-clients openldap-devel python-devel`
import ldap
from reconcile.config import get_config

_client = None
_base_dn = None

def init(server):
    global _client

    if _client is None:
        _client = ldap.initialize(server)

    return _client


def init_from_config():
    global _base_dn

    config = get_config()

    server = config['ldap']['server']
    _base_dn = config['ldap']['base_dn']

    return init(server)


def user_exists(username):

    global _client
    global _base_dn

    init_from_config()

    search_filter = "uid={}".format(username)
    
    try:
        ldap_result_id = _client.search(_base_dn, ldap.SCOPE_SUBTREE, search_filter, None)
        _, result_data = _client.result(ldap_result_id, 0)
        
        if (result_data == []):
            return False
        
        return True

    except ldap.LDAPError, e:
        print e   
