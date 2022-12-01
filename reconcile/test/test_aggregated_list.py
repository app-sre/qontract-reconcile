import pytest

from reconcile.utils.aggregated_list import (
    AggregatedDiffRunner,
    AggregatedList,
)


class TestAggregatedList:
    @staticmethod
    def test_add_item():
        alist = AggregatedList()

        params = {"a": 1, "b": 2}
        items = ["qwerty"]

        alist.add(params, items)

        assert len(alist.dump()) == 1
        assert alist.dump()[0]["items"] == items
        assert alist.dump()[0]["params"] == params

    @staticmethod
    def test_add_repeated_item():
        alist = AggregatedList()

        params = {"a": 1, "b": 2}
        item = "qwerty"
        items = [item, item]

        alist.add(params, items)

        assert len(alist.dump()) == 1
        assert alist.dump()[0]["items"] == [item]
        assert alist.dump()[0]["params"] == params

    @staticmethod
    def test_add_different_params():
        alist = AggregatedList()

        params1 = {"b": 1, "a": 2}
        items1 = ["qwerty1"]

        params2 = {"a": 1, "b": 3}
        items2 = ["qwerty2"]

        alist.add(params1, items1)
        alist.add(params2, items2)

        assert len(alist.dump()) == 2

        hp1 = AggregatedList.hash_params(params1)
        hp2 = AggregatedList.hash_params(params2)

        assert alist.get_by_params_hash(hp1)["items"] == items1
        assert alist.get_by_params_hash(hp2)["items"] == items2

    @staticmethod
    def test_get_py_params_hash():
        alist = AggregatedList()

        params1 = {"a": 1, "b": 2, "c": 3}
        params2 = {"b": 2, "c": 3, "a": 1}
        params3 = {"c": 3, "a": 1, "b": 2}
        params4 = {"a": 1, "c": 3, "b": 2}
        params5 = {"a": 1}

        items1 = ["qwerty1"]
        items2 = ["qwerty2"]

        alist.add(params1, items1)
        alist.add(params2, items1)
        alist.add(params3, items1)
        alist.add(params4, items1)
        alist.add(params5, items2)

        hp1 = AggregatedList.hash_params(params1)
        hp2 = AggregatedList.hash_params(params2)
        hp3 = AggregatedList.hash_params(params3)
        hp4 = AggregatedList.hash_params(params4)
        hp5 = AggregatedList.hash_params(params5)

        assert hp1 == hp2
        assert hp1 == hp2
        assert hp1 == hp3
        assert hp1 == hp4
        assert hp1 != hp5

        assert alist.get_by_params_hash(hp1)["items"] == items1
        assert alist.get_by_params_hash(hp5)["items"] == items2

    @staticmethod
    def test_diff_insert():
        left = AggregatedList()
        right = AggregatedList()

        right.add({"a": 1}, ["qwerty"])

        diff = left.diff(right)

        assert not diff["delete"]
        assert not diff["update-insert"]
        assert not diff["update-delete"]

        assert diff["insert"] == [{"params": {"a": 1}, "items": ["qwerty"]}]

    @staticmethod
    def test_diff_delete():
        left = AggregatedList()
        right = AggregatedList()

        left.add({"a": 1}, ["qwerty"])

        diff = left.diff(right)

        assert not diff["insert"]
        assert not diff["update-insert"]
        assert not diff["update-delete"]

        assert diff["delete"] == [{"params": {"a": 1}, "items": ["qwerty"]}]

    @staticmethod
    def test_diff_update_insert():
        left = AggregatedList()
        right = AggregatedList()

        left.add({"a": 1}, ["qwerty1"])
        right.add({"a": 1}, ["qwerty1", "qwerty2"])

        diff = left.diff(right)

        assert not diff["insert"]
        assert not diff["delete"]
        assert not diff["update-delete"]

        assert diff["update-insert"] == [{"items": ["qwerty2"], "params": {"a": 1}}]

    @staticmethod
    def test_diff_update_delete():
        left = AggregatedList()
        right = AggregatedList()

        left.add({"a": 1}, ["qwerty1", "qwerty2"])
        right.add({"a": 1}, ["qwerty1"])

        diff = left.diff(right)

        assert diff["insert"] == []
        assert diff["delete"] == []
        assert not diff["update-insert"]

        assert diff["update-delete"] == [{"items": ["qwerty2"], "params": {"a": 1}}]


class TestAggregatedDiffRunner:
    @staticmethod
    def test_run():
        left = AggregatedList()
        right = AggregatedList()

        # test insert
        right.add({"on": "insert"}, ["i"])

        # test delete
        left.add({"on": "delete"}, ["d"])

        # test update-insert
        left.add({"on": "update-insert"}, ["ui1"])
        right.add({"on": "update-insert"}, ["ui1", "ui2"])

        # test update-delete
        left.add({"on": "update-delete"}, ["ud1", "ud2"])
        right.add({"on": "update-delete"}, ["ud1"])

        on_insert = []
        on_delete = []
        on_update_insert = []
        on_update_delete = []

        def recorder(ls):
            return lambda p, i: ls.append([p, i])

        runner = AggregatedDiffRunner(left.diff(right))

        runner.register("insert", recorder(on_insert))
        runner.register("delete", recorder(on_delete))
        runner.register("update-insert", recorder(on_update_insert))
        runner.register("update-delete", recorder(on_update_delete))

        runner.run()

        assert on_insert == [[{"on": "insert"}, ["i"]]]
        assert on_delete == [[{"on": "delete"}, ["d"]]]
        assert on_update_insert == [[{"on": "update-insert"}, ["ui2"]]]
        assert on_update_delete == [[{"on": "update-delete"}, ["ud2"]]]

    @staticmethod
    def test_run_cond_true():
        left = AggregatedList()
        right = AggregatedList()

        right.add({"on": "insert"}, ["qwerty"])

        runner = AggregatedDiffRunner(left.diff(right))

        recorder = []
        runner.register("insert", lambda p, i: recorder.append("True"), lambda p: True)

        runner.run()

        assert recorder == ["True"]

    @staticmethod
    def test_run_cond_false():
        left = AggregatedList()
        right = AggregatedList()

        right.add({"on": "insert"}, ["qwerty"])

        runner = AggregatedDiffRunner(left.diff(right))

        recorder = []
        runner.register("insert", lambda p, i: recorder.append("True"), lambda p: False)

        runner.run()

        assert not recorder

    @staticmethod
    def test_unknown_diff_on():
        left = AggregatedList()
        right = AggregatedList()

        runner = AggregatedDiffRunner(left.diff(right))

        with pytest.raises(Exception):
            runner.register("qwerty", lambda p, i: True, lambda p: True)
