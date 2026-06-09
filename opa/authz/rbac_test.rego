package authz_test

import rego.v1

import data.authz

# ── Test data ────────────────────────────────────────────────────

mock_data := {
	"users": {
		"admin": ["admin-role"],
		"ldap-users-api": ["ldap-role"],
		"vcs-api": ["vcs-role"],
		"ci-bot": ["slack-chat-role"],
		"leaked-token-subject": [],
		"*": ["default-role"],
	},
	"roles": {
		"admin-role": [{"obj": "*", "params": {}}],
		"default-role": [{"obj": "liveness", "params": {}}],
		"ldap-role": [{
			"obj": "ldap-users-check",
			"params": {
				"secret.server_url": "^ldaps?://freeipa\\.example\\.com$",
				"secret.path": "^app-sre/creds/ldap",
				"secret.secret_manager_url": "^https://vault\\.example\\.com$",
			},
		}],
		"vcs-role": [{
			"obj": "vcs-repo-owners",
			"params": {
				"repo_url": "^https://(github\\.com|gitlab\\.cee\\.redhat\\.com)/",
				"path": "^app-sre/creds/",
			},
		}],
		"slack-chat-role": [{
			"obj": "slack-chat-post-message",
			"params": {"secret.path": "^app-sre/creds/slack"},
		}],
	},
}

# ── Basic authorization ──────────────────────────────────────────

test_admin_wildcard_authorized if {
	authz.authorized with input as {
		"username": "admin",
		"obj": "any-endpoint",
		"params": {"anything": "goes"},
	}
		with data.users as mock_data.users
		with data.roles as mock_data.roles
}

test_unknown_user_denied if {
	not authz.authorized with input as {
		"username": "unknown-user",
		"obj": "ldap-users-check",
		"params": {},
	}
		with data.users as {"*": []}
		with data.roles as mock_data.roles
}

test_blocked_user_denied if {
	not authz.authorized with input as {
		"username": "leaked-token-subject",
		"obj": "ldap-users-check",
		"params": {
			"secret.server_url": "ldap://freeipa.example.com",
			"secret.path": "app-sre/creds/ldap-prod",
			"secret.secret_manager_url": "https://vault.example.com",
		},
	}
		with data.users as mock_data.users
		with data.roles as mock_data.roles
}

test_default_roles_apply if {
	authz.authorized with input as {
		"username": "any-user",
		"obj": "liveness",
		"params": {},
	}
		with data.users as mock_data.users
		with data.roles as mock_data.roles
}

test_matching_obj_and_params_authorized if {
	authz.authorized with input as {
		"username": "ldap-users-api",
		"obj": "ldap-users-check",
		"params": {
			"secret.server_url": "ldap://freeipa.example.com",
			"secret.path": "app-sre/creds/ldap-prod",
			"secret.secret_manager_url": "https://vault.example.com",
		},
	}
		with data.users as mock_data.users
		with data.roles as mock_data.roles
}

test_wrong_obj_denied if {
	not authz.authorized with input as {
		"username": "ldap-users-api",
		"obj": "vcs-repo-owners",
		"params": {},
	}
		with data.users as mock_data.users
		with data.roles as mock_data.roles
}

test_wrong_params_denied if {
	not authz.authorized with input as {
		"username": "ldap-users-api",
		"obj": "ldap-users-check",
		"params": {
			"secret.server_url": "ldap://wrong-server.com",
			"secret.path": "app-sre/creds/ldap-prod",
			"secret.secret_manager_url": "https://vault.example.com",
		},
	}
		with data.users as mock_data.users
		with data.roles as mock_data.roles
}

test_case_insensitive_params if {
	authz.authorized with input as {
		"username": "ldap-users-api",
		"obj": "ldap-users-check",
		"params": {
			"secret.server_url": "LDAP://FREEIPA.EXAMPLE.COM",
			"secret.path": "APP-SRE/CREDS/LDAP-PROD",
			"secret.secret_manager_url": "HTTPS://VAULT.EXAMPLE.COM",
		},
	}
		with data.users as mock_data.users
		with data.roles as mock_data.roles
}

test_extra_params_allowed if {
	authz.authorized with input as {
		"username": "ldap-users-api",
		"obj": "ldap-users-check",
		"params": {
			"secret.server_url": "ldap://freeipa.example.com",
			"secret.path": "app-sre/creds/ldap-prod",
			"secret.secret_manager_url": "https://vault.example.com",
			"extra_param": "this-is-not-in-policy",
		},
	}
		with data.users as mock_data.users
		with data.roles as mock_data.roles
}

# ── SSRF prevention: LDAP ────────────────────────────────────────

test_ssrf_ldap_attacker_server_denied if {
	not authz.authorized with input as {
		"username": "ldap-users-api",
		"obj": "ldap-users-check",
		"params": {
			"secret.server_url": "ldap://evil.com",
			"secret.path": "app-sre/creds/ldap-prod",
			"secret.secret_manager_url": "https://vault.example.com",
		},
	}
		with data.users as mock_data.users
		with data.roles as mock_data.roles
}

test_ssrf_ldap_legit_server_allowed if {
	authz.authorized with input as {
		"username": "ldap-users-api",
		"obj": "ldap-users-check",
		"params": {
			"secret.server_url": "ldaps://freeipa.example.com",
			"secret.path": "app-sre/creds/ldap-prod",
			"secret.secret_manager_url": "https://vault.example.com",
		},
	}
		with data.users as mock_data.users
		with data.roles as mock_data.roles
}

# ── SSRF prevention: VCS ─────────────────────────────────────────

test_ssrf_vcs_attacker_repo_denied if {
	not authz.authorized with input as {
		"username": "vcs-api",
		"obj": "vcs-repo-owners",
		"params": {
			"repo_url": "https://evil.com/attacker/repo",
			"path": "app-sre/creds/github-token",
		},
	}
		with data.users as mock_data.users
		with data.roles as mock_data.roles
}

test_ssrf_vcs_legit_github_allowed if {
	authz.authorized with input as {
		"username": "vcs-api",
		"obj": "vcs-repo-owners",
		"params": {
			"repo_url": "https://github.com/app-sre/qontract-reconcile",
			"path": "app-sre/creds/github-token",
		},
	}
		with data.users as mock_data.users
		with data.roles as mock_data.roles
}

test_ssrf_vcs_legit_gitlab_allowed if {
	authz.authorized with input as {
		"username": "vcs-api",
		"obj": "vcs-repo-owners",
		"params": {
			"repo_url": "https://gitlab.cee.redhat.com/service/repo",
			"path": "app-sre/creds/gitlab-token",
		},
	}
		with data.users as mock_data.users
		with data.roles as mock_data.roles
}

# ── Vault path restriction ───────────────────────────────────────

test_arbitrary_vault_path_denied if {
	not authz.authorized with input as {
		"username": "ldap-users-api",
		"obj": "ldap-users-check",
		"params": {
			"secret.server_url": "ldap://freeipa.example.com",
			"secret.path": "other-team/secrets/aws-keys",
			"secret.secret_manager_url": "https://vault.example.com",
		},
	}
		with data.users as mock_data.users
		with data.roles as mock_data.roles
}

test_allowed_vault_path_authorized if {
	authz.authorized with input as {
		"username": "ldap-users-api",
		"obj": "ldap-users-check",
		"params": {
			"secret.server_url": "ldap://freeipa.example.com",
			"secret.path": "app-sre/creds/ldap/production",
			"secret.secret_manager_url": "https://vault.example.com",
		},
	}
		with data.users as mock_data.users
		with data.roles as mock_data.roles
}

# ── Token blocking / scoping ────────────────────────────────────

test_leaked_token_subject_denied_all_endpoints if {
	not authz.authorized with input as {
		"username": "leaked-token-subject",
		"obj": "slack-chat-post-message",
		"params": {"secret.path": "app-sre/creds/slack"},
	}
		with data.users as mock_data.users
		with data.roles as mock_data.roles
}

test_scoped_token_allowed_correct_endpoint if {
	authz.authorized with input as {
		"username": "ci-bot",
		"obj": "slack-chat-post-message",
		"params": {"secret.path": "app-sre/creds/slack-bot"},
	}
		with data.users as mock_data.users
		with data.roles as mock_data.roles
}

test_scoped_token_wrong_endpoint_denied if {
	not authz.authorized with input as {
		"username": "ci-bot",
		"obj": "vcs-repo-owners",
		"params": {
			"repo_url": "https://github.com/org/repo",
			"path": "app-sre/creds/github",
		},
	}
		with data.users as mock_data.users
		with data.roles as mock_data.roles
}
