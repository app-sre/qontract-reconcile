package authz

objects contains obj if {
	some role in data.users[input.username]
	some permission in data.roles[role]
	obj := permission.obj
}

objects contains obj if {
	some role in data.users["*"]
	some permission in data.roles[role]
	obj := permission.obj
}
