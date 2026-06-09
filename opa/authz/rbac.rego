package authz

default authorized := false

# METADATA
# description: Allow access to an action if the user has the required permissions
# entrypoint: true
# scope: document
authorized if {
	# Check if the user has specific roles
	user_roles := data.users[input.username]
	some role_name in user_roles
	check_role_permissions(data.roles[role_name], input.username, input.obj, input.params)
}

authorized if {
	# Check if there are default roles for all users
	default_roles := data.users["*"]
	some role_name in default_roles
	check_role_permissions(data.roles[role_name], input.username, input.obj, input.params)
}

check_role_permissions(role_permissions, username, current_input_obj, current_input_params) if {
	some permission in role_permissions
	object_matches(permission.obj, current_input_obj)
	valid_params(permission.params, current_input_params)
}

# Match any input if permission_obj is "*"
object_matches("*", _) := true

object_matches(permission_obj, input_obj) if {
	permission_obj == input_obj
}

valid_params(expected, provided) if {
	# Check that null values in expected mean that the key should not be present in provided
	null_keys := {k | expected[k] == null}
	every k in null_keys {
		not provided[k]
	}

	# For non-null values, ensure they match using regex
	non_null_keys := {k | expected[k] != null}
	every k in non_null_keys {
		regex.match(sprintf("(?i)%s", [expected[k]]), provided[k])
	}
}
