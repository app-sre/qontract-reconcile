from .fixtures import Fixtures

import reconcile.openshift_performance_parameters as perf_params

fxt = Fixtures('openshift_performance_parameters')


class TestOpenShiftPerfParams(object):
    def test_labels_to_selectors(self):
        items = [
            ([], ""),
            ({}, ""),
            (
                {'a': 'b', 'c': 'd'},
                r"""'a="b"', 'c="d"'"""
            ),
            (
                ['a="b"', 'c="d"'],
                r"""'a="b"', 'c="d"'"""
            ),
        ]
        for label_in, label_out in items:
            assert perf_params.labels_to_selectors(label_in) == label_out

    def test_params(self):
        t1_pp = fxt.get_anymarkup('t1-pp.yaml')
        t1_params = fxt.get_anymarkup('t1-params.yaml')
        t1_rendered = fxt.get('t1-rendered.txt')

        assert perf_params.build_template_params(t1_pp) == t1_params

        rendered = perf_params.render_template(perf_params.SLO_RULES,
                                               t1_params)
        assert rendered == t1_rendered
