import sys
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
        tfs = {}
        for name, wd in working_dirs.items():
            tf = Terraform(working_dir=wd)
            self.return_code, self.stdout, self.stderr = tf.init()
            self.check_output()
            tfs[name] = tf
        self.tfs = tfs

    def plan(self):
        for name, tf in self.tfs.items():
            self.return_code, self.stdout, self.stderr = \
                tf.plan(detailed_exitcode=False)
            self.check_output()
            self.log_plan_diff(name)

    def log_plan_diff(self, name):
        for line in self.stdout.split('\n'):
            line = line.strip()
            if line.startswith('+ aws'):
                line_split = line.replace('+ ', '').split('.')
                logging.info(['create', name, line_split[0], line_split[1]])
            if line.startswith('- aws'):
                line_split = line.replace('- ', '').split('.')
                logging.info(['destroy', name, line_split[0], line_split[1]])
            if line.startswith('~ aws'):
                line_split = line.replace('~ ', '').split('.')
                logging.info(['update', name, line_split[0], line_split[1]])
            if line.startswith('-/+ aws'):
                line_split = line.replace('-/+ ', '').split('.')
                logging.info(['REPLACE', name, line_split[0],
                              line_split[1].split(' ', 1)[0]])

    def apply(self):
        for name, tf in self.tfs.items():
            self.return_code, self.stdout, self.stderr = \
                tf.apply(auto_approve=True)
            self.check_output()

    def populate_desired_state(self, ri):
        for name, tf in self.tfs.items():
            self.output = tf.output()
            self.format_output()

            for name, data in self.output.items():
                oc_resource = self.contruct_oc_resource(name, data)
                ri.add_desired(
                    data['{}.cluster'.format(self.integration_prefix)],
                    data['{}.namespace'.format(self.integration_prefix)],
                    data['{}.resource'.format(self.integration_prefix)],
                    name,
                    oc_resource
                )

    def format_output(self):
        # data is a dictionary of dictionaries
        data = {}
        for k, v in self.output.items():
            if '[' not in k or ']' not in k:
                continue
            k_split = k.split('[')
            resource_name = k_split[0]
            field_key = k_split[1][:-1]
            field_value = v['value']
            if resource_name not in data:
                data[resource_name] = {}
            data[resource_name][field_key] = field_value
        self.output = data

    def contruct_oc_resource(self, name, data):
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

    def check_output(self):
        for line in self.stdout.split('\n'):
            if len(line) == 0:
                continue
            logging.debug(line)
        if self.return_code != 0 and len(self.stderr) != 0:
            for line in self.stderr.split('\n'):
                if len(line) == 0:
                    continue
                logging.error(self.stderr)
            self.cleanup()
            sys.exit(self.return_code)

    def cleanup(self):
        for _, wd in self.working_dirs.items():
            shutil.rmtree(wd)
