import os
import sys
from subprocess import CalledProcessError
from unittest import TestCase
from unittest.mock import patch

import reconcile.requests_sender as integ
from reconcile import (
    queries,
    typed_queries,
)


class TestRunInteg(TestCase):
    def setUp(self):
        os.environ["APP_INTERFACE_STATE_BUCKET_ACCOUNT"] = "anaccount"
        self.user = {
            "org_username": "myorg",
            "public_gpg_key": "mykey",
        }

        self.requests = [
            {
                "user": self.user,
                "credentials": "credentials_name",
                "name": "aname",
            }
        ]

        self.exit_patcher = patch.object(sys, "exit", autospec=True)
        self.get_encrypted_creds_patcher = patch.object(
            integ, "get_encrypted_credentials"
        )
        self.smtpclient_patcher = patch.object(integ, "SmtpClient", autospec=True)
        self.get_settings_patcher = patch.object(
            queries, "get_app_interface_settings", autospec=True
        )
        self.get_smtp_credentials_patcher = patch.object(
            integ, "get_smtp_server_connection", autospec=True
        )
        self.smtp_settings_patcher = patch.object(
            typed_queries.smtp, "settings", autospec=True
        )
        self.get_aws_accounts_patcher = patch.object(
            queries, "get_aws_accounts", autospec=True
        )
        self.get_credentials_requests_patcher = patch.object(
            queries, "get_credentials_requests", autospec=True
        )
        self.state_patcher = patch.object(integ, "init_state", autospec=True)
        self.vault_settings_patcher = patch.object(
            integ,
            "get_app_interface_vault_settings",
            autospec=True,
        )

        self.do_exit = self.exit_patcher.start()
        self.get_encrypted_credentials = self.get_encrypted_creds_patcher.start()
        self.smtpclient = self.smtpclient_patcher.start()
        self.get_app_interface_settings = self.get_settings_patcher.start()
        self.get_smtp_credentials = self.get_smtp_credentials_patcher.start()
        self.smtp_settings = self.smtp_settings_patcher.start()
        self.get_aws_accounts = self.get_aws_accounts_patcher.start()
        self.get_credentials_requests = self.get_credentials_requests_patcher.start()
        self.get_credentials_requests.return_value = self.requests
        self.get_encrypted_credentials.return_value = "anencryptedcred"
        self.state = self.state_patcher.start()
        self.vault_settings_patcher.start()
        self.settings = {
            "smtp": {
                "secret_path": "asecretpath",
                "server": "aserver",
                "password": "apassword",
                "port": 993,
                "require_tls": True,
                "username": "asmtpuser",
            }
        }
        self.get_app_interface_settings.return_value = self.settings
        self.get_aws_accounts.return_value = ["anaccount"]

    def tearDown(self):
        for p in (
            self.exit_patcher,
            self.get_encrypted_creds_patcher,
            self.smtpclient_patcher,
            self.get_settings_patcher,
            self.get_smtp_credentials_patcher,
            self.smtp_settings_patcher,
            self.get_credentials_requests_patcher,
            self.get_aws_accounts_patcher,
            self.state_patcher,
            self.vault_settings_patcher,
        ):
            p.stop()

    def test_valid_credentials(self):
        # Yeah, yeah, whatever
        self.state.return_value.exists.return_value = False
        integ.run(False)
        # This has succeeded
        self.do_exit.assert_not_called()
        self.get_encrypted_credentials.assert_called_once_with(
            "credentials_name", self.user, self.settings
        )
        calls = self.smtpclient.return_value.send_mail.call_args_list
        self.assertEqual(len(calls), 1)
        # I don't care too much about the body of the email, TBH
        self.assertEqual(calls[0][0][:-1], (["myorg"], "aname"))
        # Just check that we're still sending the encrypted credential
        # in the body. This assertion is backwards with regards to all
        # other assertions :(
        self.assertIn("anencryptedcred", calls[0][0][-1])

    def test_existing_credentials(self):
        self.state.return_value.exists.return_value = True
        integ.run(False)
        self.do_exit.assert_not_called()
        self.get_encrypted_credentials.assert_not_called()
        self.smtpclient.return_value.send_mail.assert_not_called()

    def test_invalid_credentials(self):
        self.get_encrypted_credentials.side_effect = CalledProcessError(
            stderr="iadaiada", returncode=1, cmd="a command"
        )
        self.state.return_value.exists.return_value = False
        integ.run(False)
        self.do_exit.assert_called_once()
        self.get_encrypted_credentials.assert_called_once()
        self.smtpclient.return_value.send_mail.assert_not_called()

    def test_dry_run_honored(self):
        self.state.return_value.exists.return_value = False
        integ.run(True)

        self.get_encrypted_credentials.assert_called_once()
        self.do_exit.assert_not_called()
        self.smtpclient.return_value.send_mail.assert_not_called()
        self.state.return_value.add.assert_not_called()
