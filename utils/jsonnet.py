import json
import subprocess


def generate(jsonnet_file_path, temp_dir_path):
    """Initializes a jsonnet directory with the provided jsonnetfile"""
    cmd = ['jsonnet', '-J', 'vendor/', jsonnet_file_path]
    return json.loads(
        subprocess.check_output(cmd, cwd=temp_dir_path)
        )


def generate_jsonnet_file(
  jsonnet_template_filename, pp, namespace,
  libsonnet_file_path, temp_dir_path, template_env
  ):
    """Generate the <component>-slo-<namespace>.jsonnet file"""
    template = template_env.get_template(jsonnet_template_filename)
    # Get some template-specific variables
    component_name = pp['component']
    namespace_name = namespace['name']
    manifestLabels = {
      'role': 'alert-rules',
    }
    manifestLabels.update(json.loads(pp['prometheusLabels']))
    selectors = []
    for k, v in json.loads(
      pp['availability'][0].get('selectors')
      ).iteritems():
        selectors.append("%s=\"%s\"" % (k, v))
    jsonnet_file_path = str(
      temp_dir_path + "/" + component_name +
      "-slo-" + namespace_name + ".jsonnet"
      )

    outputText = template.render(
      libsonnetFile=libsonnet_file_path,
      component=component_name,
      namespace=namespace_name,
      selectors=json.dumps(selectors, ensure_ascii=True),
      manifestLabels=json.dumps(manifestLabels, ensure_ascii=True)
      )

    with open(jsonnet_file_path, 'w') as f:
        f.writelines(outputText)
    f.close()

    return jsonnet_file_path


def generate_libsonnet_file(
  libsonnet_template_filename, pp, namespace, temp_dir_path, template_env
  ):
    """Generate the <component>-slo-<namespace>.libsonnet file"""
    template = template_env.get_template(libsonnet_template_filename)
    component_name = pp['component']
    namespace_name = namespace['name']
    http_metric_name = pp['availability'][0].get('metric')
    availability_error_budget = pp['availability'][0].get(
      'errorBudget'
      )
    selectors = []
    for k, v in json.loads(
      pp['availability'][0].get('selectors')
      ).iteritems():
        selectors.append("%s=\"%s\"" % (k, v))

    outputText = template.render(
      metric=http_metric_name,
      selectors=json.dumps(selectors, ensure_ascii=True),
      errorBudget=availability_error_budget
      )

    libsonnet_file_path = str(
      temp_dir_path + "/" + component_name +
      "-slo-" + namespace_name + ".libsonnet"
      )
    with open(libsonnet_file_path, 'w') as f:
        f.writelines(outputText)
    f.close()
    return libsonnet_file_path
