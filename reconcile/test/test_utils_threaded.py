import unittest
import reconcile.utils.threaded as threaded


def identity(x):
    return x


def raiser(*args, **kwargs):
    raise Exception("Oh noes!")


class TestWrappers(unittest.TestCase):

    def test_full_traceback_no_error(self):
        f = threaded.full_traceback(identity)

        self.assertEqual(f(42), 42)

    def tet_full_traceback_exception(self):
        f = threaded.full_traceback(raiser)

        with self.assertRaises(Exception):
            f(42)

    def test_catching_traceback_no_error(self):
        f = threaded.catching_traceback(identity)

        self.assertEqual(f(42), 42)

    def test_catching_traceback_exception(self):
        f = threaded.catching_traceback(raiser)

        rs = f(42)
        self.assertEqual(rs.args, ("Oh noes!", ))


class TestRunStuff(unittest.TestCase):
    def test_run_normal(self):
        rs = threaded.run(identity, [42, 43, 44], 1)
        self.assertEqual(rs, [42, 43, 44])

    def test_run_normal_with_exceptions(self):
        with self.assertRaises(Exception):
            threaded.run(raiser, [42], 1)

    def test_run_catching(self):
        rs = threaded.run(identity, [42, 43, 44], 1, return_exceptions=True)
        self.assertEqual(rs, [42, 43, 44])

    def test_run_return_exceptions(self):
        rs = threaded.run(raiser, [42], 1, return_exceptions=True)
        self.assertEqual(rs[0].args, ("Oh noes!", ))
        self.assertEqual(len(rs), 1)
