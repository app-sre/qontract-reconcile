import copy
import hashlib
import json


class OpenshiftResource(object):
    def __init__(self, body, integration, integration_version):
        self.body = body
        self.integration = integration
        self.integration_version = integration_version

    @property
    def name(self):
        return self.body['metadata']['name']

    @property
    def kind(self):
        return self.body['kind']

    def run_assert(self):
        self.name
        self.kind

    def has_qontract_annotations(self):
        try:
            annotations = self.body['metadata']['annotations']

            assert annotations['qontract.integration'] == self.integration
            assert annotations['qontract.integration_version'] == \
                self.integration_version
        except KeyError:
            return False
        except AssertionError:
            return False

        return True

    def annotate(self):
        body = self.canonicalize(self.body)
        sha256sum = self.calculate_sha256sum(self.serialize(body))

        annotations = body['metadata']['annotations']

        annotations['qontract.integration'] = self.integration
        annotations['qontract.integration_version'] = \
            self.integration_version

        annotations['qontract.sha256sum'] = sha256sum

        self.body = body

    def sha256sum(self):
        if self.has_qontract_annotations():
            try:
                annotations = self.body['metadata']['annotations']
                return annotations['qontract.sha256sum']
            except KeyError:
                pass

        # calculate sha256sum if it doesn't have annotations
        body = self.canonicalize(self.body)
        return self.calculate_sha256sum(self.serialize(body))

    @staticmethod
    def canonicalize(body):
        body = copy.deepcopy(body)

        body.setdefault('metadata', {}).setdefault('annotations', {})

        annotations = body['metadata']['annotations']

        annotations.pop('qontract.integration', None)
        annotations.pop('qontract.integration_version', None)
        annotations.pop('qontract.sha256sum', None)

        return body

    @staticmethod
    def serialize(body):
        return json.dumps(body, sort_keys=True)

    @staticmethod
    def calculate_sha256sum(body):
        m = hashlib.sha256()
        m.update(body)
        return m.hexdigest()
