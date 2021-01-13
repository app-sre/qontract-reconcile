import reconcile.prometheus_rules_tester as prt

GOOD_YAML = '''
---
$schema: /app-interface/prometheus-rule-test-1.yml
rule_files:
- /kiss.yml
evaluation_interval: 1m
'''

BAD_YAML_PARSEABLE_1 = '''
$schema: /app-interface/prometheus-rule-test-1.yml
rule_files:
- /smooth.yml
- /criminal.yml
evaluation_interval: 1m
{{% if lol %}}
lol_key: lol_value
{{% end %}}
'''

BAD_YAML_PARSEABLE_2 = '''
$schema: /app-interface/prometheus-rule-test-1.yml
rule_files:
  - /let.yml
  - /love.yml
  - /rule.yml
evaluation_interval: 1m
{{% if lol %}}
lol_key: lol_value
{{% end %}}
'''

BAD_YAML_NON_PARSEABLE = '''
$schema: /app-interface/prometheus-rule-test-1.yml
rule_files: ['rata.yml', 'de.yml', 'dos.yml', 'patas.yml']
evaluation_interval: 1m
{{% if lol %}}
lol_key: lol_value
{{% end %}}
'''


class TestGetRuleFilesFromJinjaTestTemplate(object):
    def test_good_yaml(self):
        rule_files = prt.get_rule_files_from_jinja_test_template(GOOD_YAML)
        assert rule_files == ['/kiss.yml']

    def test_bad_yaml_parseable_1(self):
        rule_files = \
            prt.get_rule_files_from_jinja_test_template(BAD_YAML_PARSEABLE_1)
        assert rule_files == ['/smooth.yml', '/criminal.yml']

    def test_bad_yaml_parseable_2(self):
        rule_files = \
            prt.get_rule_files_from_jinja_test_template(BAD_YAML_PARSEABLE_2)
        assert rule_files == ['/let.yml', '/love.yml', '/rule.yml']

    def test_bad_yaml_non_parseable(self):
        rule_files = \
            prt.get_rule_files_from_jinja_test_template(BAD_YAML_NON_PARSEABLE)
        assert rule_files == []
