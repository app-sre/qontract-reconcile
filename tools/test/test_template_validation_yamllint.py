import pytest
from yamllint import linter
from yamllint.config import YamlLintConfig


@pytest.mark.parametrize(
    "yaml_input, config_text, expected_problem",
    [
        pytest.param(
            "---\nkey: value\n",
            "extends: default",
            None,
            id="valid-yaml",
        ),
        pytest.param(
            "key: value\nkey: duplicate\n",
            "extends: default",
            "duplication",
            id="duplicate-key",
        ),
        pytest.param(
            "key: this is a very long value\n",
            "rules:\n  line-length:\n    max: 10\n",
            "line too long",
            id="line-too-long",
        ),
    ],
)
def test_yamllint_linting(
    yaml_input: str,
    config_text: str,
    expected_problem: str | None,
) -> None:
    config = YamlLintConfig(config_text)
    problems = list(linter.run(yaml_input, config, ""))
    if expected_problem is None:
        assert not problems
    else:
        assert any(expected_problem in p.desc for p in problems)


def test_lint_problem_attributes() -> None:
    config = YamlLintConfig("rules:\n  trailing-spaces: enable\n")
    problems = list(linter.run("key: value   \n", config, ""))
    assert len(problems) >= 1
    assert problems[0].line > 0
    assert isinstance(problems[0].desc, str)
