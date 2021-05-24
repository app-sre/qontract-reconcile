import logging

from reconcile.jenkins_job_builder import get_openshift_saas_deploy_job_name


def trigger(options):
    """Trigger a deployment according to the specified pipelines provider

    Args:
        options (dict): A dictionary containing:
            dry_run (bool): Is this a dry run
            saasherder (SaasHerder): a SaasHerder class instance
            spec (dict): A trigger spec as created by saasherder
            jenkins_map (dict): Instance names with JenkinsApi instances
            already_triggered (list): A list of already triggered deployments
            settings (dict): App-interface settings
            state_update_method (function): A method to call to update state

    Returns:
        bool: True if there was an error, False otherwise
    """
    dry_run = options['dry_run']
    saasherder = options['saasherder']
    spec = options['spec']
    jenkins_map = options['jenkins_map']
    already_triggered = options['already_triggered']
    settings = options['settings']
    state_update_method = options['state_update_method']

    saas_file_name = spec['saas_file_name']
    env_name = spec['env_name']
    pipelines_provider = spec['pipelines_provider']
    provider_name = pipelines_provider['provider']

    error = False
    if provider_name == 'jenkins':
        instance_name = spec['instance_name']
        job_name = get_openshift_saas_deploy_job_name(
            saas_file_name, env_name, settings)
        if job_name not in already_triggered:
            logging.info(['trigger_job', instance_name, job_name])
            if dry_run:
                already_triggered.append(job_name)

        if not dry_run:
            jenkins = jenkins_map[instance_name]
            try:
                if job_name not in already_triggered:
                    jenkins.trigger_job(job_name)
                    already_triggered.append(job_name)
                state_update_method(spec)
            except Exception as e:
                error = True
                logging.error(
                    f"could not trigger job {job_name} " +
                    f"in {instance_name}. details: {str(e)}"
                )
    elif provider_name == 'tekton':
        raise NotImplementedError('trigger base tekton provider')
    else:
        logging.error(
            f'[{saas_file_name}] unsupported provider: ' +
            f'{provider_name}'
        )

    return error
