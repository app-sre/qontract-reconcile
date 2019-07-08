import sys

from jenkins_jobs.builder import JenkinsManager
from jenkins_jobs.parser import YamlParser
from jenkins_jobs.registry import ModuleRegistry
from jenkins_jobs.cli.entry import JenkinsJobs
from jenkins_jobs.cli.subcommand.test import TestSubCommand

def run(dry_run=False):
    argv = ['--conf', '/home/mafriedm/.config/jjb/ci-int.ini', 'test', 'jjb-ci-int.yaml']
    jjb = JenkinsJobs(argv)

    builder = JenkinsManager(jjb.jjb_config)
    registry = ModuleRegistry(jjb.jjb_config, builder.plugins_list)
    parser = YamlParser(jjb.jjb_config)
    parser.load_files(jjb.options.path)


    jobs, views = parser.expandYaml(
        registry, jjb.options.names)

    for job in jobs:
        print(job['name'])
        try:
            project_url = job['properties'][0]['github']['url']
            print(project_url)
        except KeyError:
            print('###################################')
            continue
