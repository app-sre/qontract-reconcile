import logging
import json
import hashlib
from ruamel import yaml

from reconcile.utils.mr.base import MergeRequestBase
from reconcile.utils.mr.labels import AUTO_MERGE


LOG = logging.getLogger(__name__)


class AutoPromoter(MergeRequestBase):

    name = 'auto_promoter'

    def __init__(self, promotions):
        self.promotions = promotions

        super().__init__()

        self.labels = [AUTO_MERGE]

    @property
    def title(self):
        """
        to make the MR title unique, add a sha256sum of the promotions to it
        TODO: while adding a digest ensures uniqueness, this title is
              still not very descriptive
        """
        m = hashlib.sha256()
        m.update(json.dumps(self.promotions, sort_keys=True).encode("utf-8"))
        digest = m.hexdigest()[:6]
        return (f'[{self.name}] openshift-saas-deploy automated '
                f'promotion {digest}')

    def process(self, gitlab_cli):
        for item in self.promotions:
            saas_file_paths = item.get('saas_file_paths')
            if not saas_file_paths:
                continue
            publish = item.get('publish')
            if not publish:
                continue
            commit_sha = item.get('commit_sha')
            if not commit_sha:
                continue
            for saas_file_path in saas_file_paths:
                saas_file_updated = False
                raw_file = gitlab_cli.project.files.get(
                    file_path=saas_file_path,
                    ref=self.branch
                )
                content = yaml.load(raw_file.decode(),
                                    Loader=yaml.RoundTripLoader)
                for rt in content['resourceTemplates']:
                    for target in rt['targets']:
                        target_promotion = target.get('promotion')
                        if not target_promotion:
                            continue
                        target_auto = target_promotion.get('auto')
                        if not target_auto:
                            continue
                        subscribe = target_promotion.get('subscribe')
                        if not subscribe:
                            continue
                        if any(c in subscribe for c in publish):
                            if target['ref'] != commit_sha:
                                target['ref'] = commit_sha
                                saas_file_updated = True

                if saas_file_updated:
                    new_content = '---\n'
                    new_content += yaml.dump(content,
                                             Dumper=yaml.RoundTripDumper)
                    msg = f'auto promote {commit_sha} in {saas_file_path}'
                    gitlab_cli.update_file(branch_name=self.branch,
                                           file_path=saas_file_path,
                                           commit_message=msg,
                                           content=new_content)
                else:
                    LOG.info(f"commit sha {commit_sha} has already been "
                             f"promoted to all targets in {content['name']} "
                             f"subscribing to {','.join(item['publish'])}")
