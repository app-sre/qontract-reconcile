from yamllint import linter
from yamllint.config import YamlLintConfig


def test_yamllint_valid_yaml() -> None:
    config = YamlLintConfig("extends: default")
    problems = list(linter.run("---\nkey: value\n", config, ""))
    assert not problems


def test_yamllint_invalid_yaml() -> None:
    config = YamlLintConfig("extends: default")
    problems = list(linter.run("key: value\nkey: duplicate\n", config, ""))
    assert any("duplication" in p.desc for p in problems)


def test_yamllint_config_from_content() -> None:
    config = YamlLintConfig("rules:\n  line-length:\n    max: 10\n")
    problems = list(linter.run("key: this is a very long value\n", config, ""))
    assert any("line too long" in p.desc for p in problems)


def test_lint_problem_attributes() -> None:
    config = YamlLintConfig("rules:\n  trailing-spaces: enable\n")
    problems = list(linter.run("key: value   \n", config, ""))
    assert len(problems) >= 1
    assert problems[0].line > 0
    assert isinstance(problems[0].desc, str)
