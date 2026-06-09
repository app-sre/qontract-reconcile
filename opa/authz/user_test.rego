package authz_test

import rego.v1

import data.authz

# ── Test data ────────────────────────────────────────────────────

mock_users := {
	"ldap-users-api": ["ldap-role"],
	"admin": ["admin-role"],
	"*": ["default-role"],
}

mock_roles := {
	"admin-role": [{"obj": "*", "params": {}}],
	"default-role": [{"obj": "liveness", "params": {}}],
	"ldap-role": [{
		"obj": "ldap-users-check",
		"params": {"secret.path": "^app-sre/creds/ldap"},
	}],
}

# ── Objects rule tests ───────────────────────────────────────────

test_user_objects_include_role_objs if {
	objects := authz.objects with input as {"username": "ldap-users-api"}
		with data.users as mock_users
		with data.roles as mock_roles
	"ldap-users-check" in objects
	"liveness" in objects
}

test_admin_objects_include_wildcard if {
	objects := authz.objects with input as {"username": "admin"}
		with data.users as mock_users
		with data.roles as mock_roles
	"*" in objects
	"liveness" in objects
}

test_unknown_user_gets_default_objs_only if {
	objects := authz.objects with input as {"username": "unknown-user"}
		with data.users as mock_users
		with data.roles as mock_roles
	"liveness" in objects
	not "ldap-users-check" in objects
	not "*" in objects
}
