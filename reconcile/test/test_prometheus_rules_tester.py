import reconcile.prometheus_rules_tester as prt

GOOD_YAML = """
---
$schema: /app-interface/prometheus-rule-test-1.yml
rule_files:
- /kiss.yml
evaluation_interval: 1m
"""

BAD_YAML_PARSEABLE_1 = """
$schema: /app-interface/prometheus-rule-test-1.yml
target_clusters:
- /mr.yml
- /jack.yml
rule_files:
- /smooth.yml
- /criminal.yml
evaluation_interval: 1m
{{% if lol %}}
lol_key: lol_value
{{% end %}}
"""

BAD_YAML_PARSEABLE_2 = """
$schema: /app-interface/prometheus-rule-test-1.yml
rule_files:
  - /let.yml
  - /love.yml
  - /rule.yml
evaluation_interval: 1m
{{% if lol %}}
lol_key: lol_value
{{% end %}}
"""

BAD_YAML_NON_PARSEABLE = """
$schema: /app-interface/prometheus-rule-test-1.yml
rule_files: ['rata.yml', 'de.yml', 'dos.yml', 'patas.yml']
evaluation_interval: 1m
{{% if lol %}}
lol_key: lol_value
{{% end %}}
"""


class TestGetRuleFilesFromJinjaTestTemplate:
    @staticmethod
    def test_good_yaml():
        data = prt.get_data_from_jinja_test_template(
            GOOD_YAML, ["rule_files", "target_clusters"]
        )
        assert data["rule_files"] == ["/kiss.yml"]
        assert data["target_clusters"] == []

    @staticmethod
    def test_bad_yaml_parseable_1():
        data = prt.get_data_from_jinja_test_template(
            BAD_YAML_PARSEABLE_1, ["rule_files", "target_clusters"]
        )
        assert data["rule_files"] == ["/smooth.yml", "/criminal.yml"]
        assert data["target_clusters"] == ["/mr.yml", "/jack.yml"]

    @staticmethod
    def test_bad_yaml_parseable_2():
        data = prt.get_data_from_jinja_test_template(
            BAD_YAML_PARSEABLE_2, ["rule_files"]
        )

        assert data["rule_files"] == ["/let.yml", "/love.yml", "/rule.yml"]

    @staticmethod
    def test_bad_yaml_non_parseable():
        data = prt.get_data_from_jinja_test_template(
            BAD_YAML_NON_PARSEABLE, ["rule_files"]
        )
        assert data["rule_files"] == []
