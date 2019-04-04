import shutil
import base64
import logging

from utils.openshift_resource import OpenshiftResource

from python_terraform import Terraform


class ConstructResourceError(Exception):
    def __init__(self, msg):
        super(ConstructResourceError, self).__init__(
            "error construction openshift resource: " + str(msg)
        )


class OR(OpenshiftResource):
    def __init__(self, body, integration, integration_version):
        super(OR, self).__init__(
            body, integration, integration_version
        )


class TerraformClient(object):
    def __init__(self, integration, integration_version,
                 integration_prefix, working_dirs):
        self.integration = integration
        self.integration_version = integration_version
        self.integration_prefix = integration_prefix
        self.working_dirs = working_dirs
        self.OUTPUT_TYPE_SECRETS = 'Secrets'
        self.OUTPUT_TYPE_PASSWORDS = 'enc-passwords'
        self.OUTPUT_TYPE_CONSOLEURLS = 'console-urls'
        tfs = {}
        console_urls = {}
        for name, wd in working_dirs.items():
            tf = Terraform(working_dir=wd)
            console_url = ''
            return_code, stdout, stderr = tf.init()
            error = self.check_output(name, return_code, stdout, stderr)
            if error:
                return None
            tfs[name] = tf
            console_urls[name] = console_url
        self.tfs = tfs
        self.get_existing_users()

    def get_existing_users(self):
        all_users = {}
        for account, tf in self.tfs.items():
            users = []
            output = tf.output()
            user_passwords = self.format_output(
                output, self.OUTPUT_TYPE_PASSWORDS)
            for user_name in user_passwords:
                users.append(user_name)
            all_users[account] = users
        self.users = all_users

    def get_new_users(self):
        new_users = []
        for account, tf in self.tfs.items():
            existing_users = self.users[account]
            output = tf.output()
            user_passwords = self.format_output(
                output, self.OUTPUT_TYPE_PASSWORDS)
            console_urls = self.format_output(
                output, self.OUTPUT_TYPE_CONSOLEURLS)
            for user_name, enc_password in user_passwords.items():
                if user_name in existing_users:
                    continue
                new_users.append((account, console_urls[account],
                                  user_name, enc_password))
        return new_users

    def plan(self, enable_deletion):
        errors = False
        deletions_detected = False
        for name, tf in self.tfs.items():
            return_code, stdout, stderr = tf.plan(detailed_exitcode=False)
            error = self.check_output(name, return_code, stdout, stderr)
            if error:
                errors = True
            deletion_detected = \
                self.log_plan_diff(name, stdout, enable_deletion)
            if deletion_detected:
                deletions_detected = True
        return deletions_detected, errors

    def log_plan_diff(self, name, stdout, enable_deletion):
        deletions_detected = False
        stdout = self.split_to_lines(stdout)
        for line in stdout:
            line = line.strip()
            if line.startswith('+ aws'):
                line_split = line.replace('+ ', '').split('.')
                logging.info(['create', name, line_split[0], line_split[1]])
            if line.startswith('- aws'):
                line_split = line.replace('- ', '').split('.')
                if enable_deletion:
                    logging.info(['destroy', name,
                                  line_split[0], line_split[1]])
                else:
                    logging.error(['destroy', name,
                                   line_split[0], line_split[1]])
                    logging.error('\'destroy\' action is not enabled. ' +
                                  'Please run the integration manually ' +
                                  'with the \'--enable-deletion\' flag.')
                deletions_detected = True
            if line.startswith('~ aws'):
                line_split = line.replace('~ ', '').split('.')
                logging.info(['update', name, line_split[0], line_split[1]])
            if line.startswith('-/+ aws'):
                line_split = line.replace('-/+ ', '').split('.')
                if enable_deletion:
                    logging.info(['replace', name, line_split[0],
                                  line_split[1].split(' ', 1)[0]])
                else:
                    logging.error(['replace', name, line_split[0],
                                   line_split[1].split(' ', 1)[0]])
                    logging.error('\'replace\' action is not enabled. ' +
                                  'Please run the integration manually ' +
                                  'with the \'--enable-deletion\' flag.')
                deletions_detected = True
        return deletions_detected

    def apply(self):
        errors = False
        for name, tf in self.tfs.items():
            return_code, stdout, stderr = tf.apply(auto_approve=True)
            error = self.check_output(name, return_code, stdout, stderr)
            if error:
                errors = True
        return errors

    def populate_desired_state(self, ri):
        for name, tf in self.tfs.items():
            output = tf.output()
            formatted_output = self.format_output(
                output, self.OUTPUT_TYPE_SECRETS)

            for name, data in formatted_output.items():
                oc_resource = self.construct_oc_resource(name, data)
                ri.add_desired(
                    data['{}.cluster'.format(self.integration_prefix)],
                    data['{}.namespace'.format(self.integration_prefix)],
                    data['{}.resource'.format(self.integration_prefix)],
                    name,
                    oc_resource
                )

    def format_output(self, output, type):
        # data is a dictionary of dictionaries
        data = {}
        if output is None:
            return data

        enc_pass_pfx = '{}.{}'.format(
            self.integration_prefix, self.OUTPUT_TYPE_PASSWORDS)
        console_urls_pfx = '{}.{}'.format(
            self.integration_prefix, self.OUTPUT_TYPE_CONSOLEURLS)
        for k, v in output.items():
            # the integration creates outputs of the form
            # output_secret_name[secret_key] = secret_value
            # in case of manual debugging, additional outputs
            # may be added, and may (should) not conform to this
            # naming convention. as outputs are persisted to remote
            # state, we would not want them to affect any runs
            # of the integration.
            if '[' not in k or ']' not in k:
                continue

            # if the output is of the form 'qrtf.enc-passwords[user_name]'
            # this is a user output and should not be formed to a Secret
            # but rather to an invitaion e-mail.
            # this is determined by the 'type' argument
            if type == self.OUTPUT_TYPE_PASSWORDS and \
                    not k.startswith(enc_pass_pfx):
                continue

            if type == self.OUTPUT_TYPE_CONSOLEURLS and \
                    not k.startswith(console_urls_pfx):
                continue

            # Secrets is in essence the default value
            # because we don't (currently) have a way
            # to clasify it (secret names are free text)
            if type == self.OUTPUT_TYPE_SECRETS and (
                k.startswith(enc_pass_pfx) or
                k.startswith(console_urls_pfx)
            ):
                continue

            k_split = k.split('[')
            resource_name = k_split[0]
            field_key = k_split[1][:-1]
            field_value = v['value']
            if resource_name not in data:
                data[resource_name] = {}
            data[resource_name][field_key] = field_value

        if len(data) == 1 and type in (
            self.OUTPUT_TYPE_PASSWORDS,
            self.OUTPUT_TYPE_CONSOLEURLS
        ):
            return data[data.keys()[0]]
        return data

    def construct_oc_resource(self, name, data):
        body = {
            "apiVersion": "v1",
            "kind": "Secret",
            "type": "Opaque",
            "metadata": {
                "name": name,
            },
            "data": {}
        }

        for k, v in data.items():
            if self.integration_prefix in k:
                continue
            body['data'][k] = base64.b64encode(v)

        openshift_resource = \
            OR(body, self.integration, self.integration_version)

        try:
            openshift_resource.verify_valid_k8s_object()
        except (KeyError, TypeError) as e:
            k = e.__class__.__name__
            e_msg = "Invalid data ({}). Skipping resource: {}"
            raise ConstructResourceError(e_msg.format(k, name))

        return openshift_resource

    def check_output(self, name, return_code, stdout, stderr):
        error_occured = False
        stdout, stderr = self.split_to_lines(stdout, stderr)
        line_format = '[{}] {}'
        for line in stdout:
            # this line will be present when performing 'terraform apply'
            # as it will contain sensitive information, skip printing
            if line.startswith('Outputs:'):
                break
            logging.info(line_format.format(name, line))
        if return_code == 0:
            for line in stderr:
                logging.warning(line_format.format(name, line))
        else:
            for line in stderr:
                logging.error(line_format.format(name, line))
            error_occured = True
        return error_occured

    def split_to_lines(self, *outputs):
        split_outputs = []
        try:
            for output in outputs:
                output_lines = [l for l in output.split('\n') if len(l) != 0]
                split_outputs.append(output_lines)
        except Exception:
            logging.warning("failed to split outputs to lines.")
            return outputs
        if len(split_outputs) == 1:
            return split_outputs[0]
        return split_outputs

    def cleanup(self):
        for _, wd in self.working_dirs.items():
            shutil.rmtree(wd)
