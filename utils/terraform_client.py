import shutil
import base64
import logging
import json
import os

from threading import Lock

from python_terraform import Terraform, IsFlagged, TerraformCommandError
from sretoolbox.utils import retry

from utils import threaded
from utils.openshift_resource import OpenshiftResource as OR


class TerraformClient(object):
    def __init__(self, integration, integration_version,
                 integration_prefix, working_dirs, thread_pool_size,
                 init_users=False):
        self.integration = integration
        self.integration_version = integration_version
        self.integration_prefix = integration_prefix
        self.working_dirs = working_dirs
        self.parallelism = thread_pool_size
        self.thread_pool_size = thread_pool_size
        self._log_lock = Lock()

        self.init_specs()
        self.init_outputs()

        self.OUTPUT_TYPE_SECRETS = 'Secrets'
        self.OUTPUT_TYPE_PASSWORDS = 'enc-passwords'
        self.OUTPUT_TYPE_CONSOLEURLS = 'console-urls'

        if init_users:
            self.init_existing_users()

    def init_existing_users(self):
        all_users = {}
        for account, output in self.outputs.items():
            users = []
            user_passwords = self.format_output(
                output, self.OUTPUT_TYPE_PASSWORDS)
            for user_name in user_passwords:
                users.append(user_name)
            all_users[account] = users
        self.users = all_users

    def get_new_users(self):
        new_users = []
        self.init_outputs()  # get updated output
        for account, output in self.outputs.items():
            existing_users = self.users[account]
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

    def init_specs(self):
        wd_specs = \
            [{'name': name, 'wd': wd}
             for name, wd in self.working_dirs.items()]
        results = threaded.run(self.terraform_init, wd_specs,
                               self.thread_pool_size)
        self.specs = \
            [{'name': name, 'tf': tf} for name, tf in results]

    @retry(exceptions=TerraformCommandError)
    def terraform_init(self, init_spec):
        name = init_spec['name']
        wd = init_spec['wd']
        tf = Terraform(working_dir=wd)
        return_code, stdout, stderr = tf.init()
        error = self.check_output(name, return_code, stdout, stderr)
        if error:
            raise TerraformCommandError(
                return_code, 'init', out=stdout, err=stderr)
        return name, tf

    def init_outputs(self):
        results = threaded.run(self.terraform_output, self.specs,
                               self.thread_pool_size)
        self.outputs = {name: output for name, output in results}

    @retry(exceptions=TerraformCommandError)
    def terraform_output(self, spec):
        name = spec['name']
        tf = spec['tf']
        return_code, stdout, stderr = tf.output_cmd(json=IsFlagged)
        error = self.check_output(name, return_code, stdout, stderr)
        no_output_error = \
            'The module root could not be found. There is nothing to output.'
        if error:
            if no_output_error in stderr:
                stdout = '{}'
            else:
                raise TerraformCommandError(
                    return_code, 'output', out=stdout, err=stderr)
        return name, json.loads(stdout)

    # terraform plan
    def plan(self, enable_deletion):
        errors = False
        deletions_detected = False
        results = threaded.run(self.terraform_plan, self.specs,
                               self.thread_pool_size,
                               enable_deletion=enable_deletion)

        self.deleted_users = []
        for deletion_detected, deleted_users, error in results:
            if error:
                errors = True
            if deletion_detected:
                deletions_detected = True
                self.deleted_users.extend(deleted_users)
        return deletions_detected, errors

    def dump_deleted_users(self, io_dir):
        if not self.deleted_users:
            return
        if not os.path.exists(io_dir):
            os.makedirs(io_dir)
        file_path = os.path.join(io_dir, self.integration + '.json')
        with open(file_path, 'w') as f:
            f.write(json.dumps(self.deleted_users))

    def terraform_plan(self, plan_spec, enable_deletion):
        name = plan_spec['name']
        tf = plan_spec['tf']
        return_code, stdout, stderr = tf.plan(detailed_exitcode=False,
                                              parallelism=self.parallelism)
        error = self.check_output(name, return_code, stdout, stderr)
        deletion_detected, deleted_users = \
            self.log_plan_diff(name, stdout, enable_deletion)
        return deletion_detected, deleted_users, error

    def log_plan_diff(self, name, stdout, enable_deletion):
        deletions_detected = False
        deleted_users = []
        stdout = self.split_to_lines(stdout)
        with self._log_lock:
            for line in stdout:
                line = line.strip()
                if line.startswith('+ aws'):
                    resource_type, resource_name = \
                        line.replace('+ ', '').split('.')
                    logging.info(['create', name,
                                  resource_type, resource_name])
                if line.startswith('- aws'):
                    resource_type, resource_name = \
                        line.replace('- ', '').split('.')
                    if enable_deletion:
                        logging.info(['destroy', name,
                                      resource_type, resource_name])
                        if resource_type == 'aws_iam_user':
                            deleted_users.append({
                                'account': name,
                                'user': resource_name
                            })
                    else:
                        logging.error(['destroy', name,
                                       resource_type, resource_name])
                        logging.error('\'destroy\' action is not enabled. ' +
                                      'Please run the integration manually ' +
                                      'with the \'--enable-deletion\' flag.')
                    deletions_detected = True
                if line.startswith('~ aws'):
                    resource_type, resource_name = \
                        line.replace('~ ', '').split('.')
                    logging.info(['update', name,
                                  resource_type, resource_name])
                if line.startswith('-/+ aws'):
                    resource_type, resource_name = \
                        line.replace('-/+ ', '').split('.')
                    resource_name = resource_name.split(' ', 1)[0]
                    if enable_deletion:
                        logging.info(['replace', name,
                                      resource_type, resource_name])
                    else:
                        logging.error(['replace', name,
                                       resource_type, resource_name])
                        logging.error('\'replace\' action is not enabled. ' +
                                      'Please run the integration manually ' +
                                      'with the \'--enable-deletion\' flag.')
                    deletions_detected = True
        return deletions_detected, deleted_users

    # terraform apply
    def apply(self):
        errors = False

        results = threaded.run(self.terraform_apply, self.specs,
                               self.thread_pool_size)

        for error in results:
            if error:
                errors = True
        return errors

    def terraform_apply(self, apply_spec):
        name = apply_spec['name']
        tf = apply_spec['tf']
        return_code, stdout, stderr = tf.apply(auto_approve=True,
                                               skip_plan=True)
        error = self.check_output(name, return_code, stdout, stderr)
        return error

    def get_terraform_output_secrets(self):
        data = {}
        for account, output in self.outputs.items():
            data[account] = \
                self.format_output(output, self.OUTPUT_TYPE_SECRETS)

        return data

    def populate_desired_state(self, ri, oc_map):
        self.init_outputs()  # get updated output
        for account, output in self.outputs.items():
            formatted_output = self.format_output(
                output, self.OUTPUT_TYPE_SECRETS)

            for name, data in formatted_output.items():
                cluster = data['{}.cluster'.format(self.integration_prefix)]
                if not oc_map.get(cluster):
                    continue
                namespace = \
                    data['{}.namespace'.format(self.integration_prefix)]
                resource = data['{}.resource'.format(self.integration_prefix)]
                output_resource_name = data['{}.output_resource_name'.format(
                    self.integration_prefix)]
                oc_resource = \
                    self.construct_oc_resource(output_resource_name, data)
                ri.add_desired(
                    cluster,
                    namespace,
                    resource,
                    output_resource_name,
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
            return data[list(data.keys())[0]]
        return data

    def construct_oc_resource(self, name, data):
        body = {
            "apiVersion": "v1",
            "kind": "Secret",
            "type": "Opaque",
            "metadata": {
                "name": name,
                "annotations": {
                    "qontract.recycle": "true"
                }
            },
            "data": {}
        }

        for k, v in data.items():
            if self.integration_prefix in k:
                continue
            if v == "":
                v = None
            else:
                v = base64.b64encode(v.encode()).decode('utf-8')
            body['data'][k] = v

        return OR(body, self.integration, self.integration_version,
                  error_details=name)

    def check_output(self, name, return_code, stdout, stderr):
        error_occured = False
        line_format = '[{}] {}'
        stdout, stderr = self.split_to_lines(stdout, stderr)
        with self._log_lock:
            for line in stdout:
                # this line will be present when performing 'terraform apply'
                # as it will contain sensitive information, skip printing
                if line.startswith('Outputs:'):
                    break
                logging.debug(line_format.format(name, line))
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
