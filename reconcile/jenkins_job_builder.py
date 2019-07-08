import sys

from jenkins_jobs.cli.entry import JenkinsJobs
from jenkins_jobs.cli.subcommand.test import TestSubCommand

def run(dry_run=False):
    argv = ['--conf', '/home/mafriedm/.config/jjb/ci-int.ini', 'test', 'jjb-ci-int.yaml']
    jjb = JenkinsJobs(argv)
    test = TestSubCommand()

    _, xml_jobs, _ = test._generate_xmljobs(
        jjb.options, jjb.jjb_config)

    for job in xml_jobs:
        print(job.name)
        try:
            project_url = job.xml[9][0][0].text
            print(project_url)
        except:
            print("NO PROJECT URL")
