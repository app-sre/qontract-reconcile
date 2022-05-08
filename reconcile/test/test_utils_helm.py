import pytest
import yaml
from reconcile.utils import helm

from .fixtures import Fixtures


fxt = Fixtures("helm")


@pytest.fixture
def values():
    return {
        "integrations": [
            {
                "name": "integ",
                "resources": {
                    "requests": {
                        "cpu": "123",
                        "memory": "45Mi",
                    },
                    "limits": {
                        "cpu": "678",
                        "memory": "90Mi",
                    },
                },
            }
        ]
    }


def test_template_basic(values):
    template = helm.template(values)
    expected = yaml.safe_load(fxt.get("basic.yml"))
    assert template == expected
