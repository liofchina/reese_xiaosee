"""OrchestrationGraph 单元测试"""
import asyncio

import pytest
from unittest.mock import AsyncMock

from domain.orchestrator import OrchestrationGraph, AgentNode


class TestTopologicalSort:
    def _make_graph(self, nodes: dict[str, list[str]]) -> OrchestrationGraph:
        graph = OrchestrationGraph()
        for name, deps in nodes.items():
            graph.add_node(name, AgentNode(
                name=name,
                execute=AsyncMock(return_value=f"result_{name}"),
                depends_on=deps,
            ))
        return graph

    def test_linear_chain(self):
        graph = self._make_graph({"a": [], "b": ["a"], "c": ["b"]})
        order = graph._topological_sort()
        assert order.index("a") < order.index("b") < order.index("c")

    def test_diamond_dag(self):
        graph = self._make_graph({"a": [], "b": ["a"], "c": ["a"], "d": ["b", "c"]})
        order = graph._topological_sort()
        assert order.index("a") < order.index("b")
        assert order.index("a") < order.index("c")
        assert order.index("b") < order.index("d")
        assert order.index("c") < order.index("d")

    def test_cycle_detection(self):
        graph = self._make_graph({"a": ["b"], "b": ["a"]})
        with pytest.raises(ValueError, match="循环依赖"):
            graph._topological_sort()

    def test_single_node(self):
        graph = self._make_graph({"a": []})
        assert graph._topological_sort() == ["a"]

    def test_independent_nodes(self):
        graph = self._make_graph({"a": [], "b": [], "c": []})
        order = graph._topological_sort()
        assert set(order) == {"a", "b", "c"}

    def test_caches_result(self):
        graph = self._make_graph({"a": [], "b": ["a"]})
        order1 = graph._topological_sort()
        order2 = graph._topological_sort()
        assert order1 is order2

    def test_cache_cleared_on_add_node(self):
        graph = self._make_graph({"a": [], "b": ["a"]})
        graph._topological_sort()
        graph.add_node("c", AgentNode(name="c", execute=AsyncMock(), depends_on=["b"]))
        order = graph._topological_sort()
        assert "c" in order


class TestFindParallelGroups:
    def _make_graph(self, nodes: dict[str, list[str]]) -> OrchestrationGraph:
        graph = OrchestrationGraph()
        for name, deps in nodes.items():
            graph.add_node(name, AgentNode(
                name=name,
                execute=AsyncMock(),
                depends_on=deps,
            ))
        return graph

    def test_all_independent(self):
        graph = self._make_graph({"a": [], "b": [], "c": []})
        groups = graph._find_parallel_groups()
        assert len(groups) == 1
        assert set(groups[0]) == {"a", "b", "c"}

    def test_all_sequential(self):
        graph = self._make_graph({"a": [], "b": ["a"], "c": ["b"]})
        groups = graph._find_parallel_groups()
        assert groups == [["a"], ["b"], ["c"]]

    def test_mixed_dependencies(self):
        graph = self._make_graph({"a": [], "b": ["a"], "c": ["a"], "d": ["b", "c"]})
        groups = graph._find_parallel_groups()
        assert groups[0] == ["a"]
        assert set(groups[1]) == {"b", "c"}
        assert groups[2] == ["d"]


class TestRun:
    @pytest.mark.asyncio
    async def test_skips_condition_false(self):
        graph = OrchestrationGraph()
        executed = []

        async def track_a(ctx):
            executed.append("a")

        async def track_b(ctx):
            executed.append("b")

        graph.add_node("a", AgentNode(
            name="a", execute=track_a,
            depends_on=[], condition=lambda ctx: False,
        ))
        graph.add_node("b", AgentNode(
            name="b", execute=track_b,
            depends_on=[],
        ))
        await graph.run({})
        assert "a" not in executed
        assert "b" in executed

    @pytest.mark.asyncio
    async def test_context_passing(self):
        graph = OrchestrationGraph()

        async def produce(ctx):
            return "hello"

        graph.add_node("a", AgentNode(
            name="a", execute=produce, depends_on=[],
        ))
        ctx = {}
        results = await graph.run(ctx)
        assert ctx["result_a"] == "hello"
        assert results["a"] == "hello"

    @pytest.mark.asyncio
    async def test_cancel_event_stops_execution(self):
        graph = OrchestrationGraph()

        async def step(ctx):
            return "done"

        graph.add_node("a", AgentNode(name="a", execute=step, depends_on=[]))
        graph.add_node("b", AgentNode(name="b", execute=step, depends_on=["a"]))

        cancel = asyncio.Event()
        cancel.set()  # 立即取消
        results = await graph.run({}, cancel_event=cancel)
        assert "b" not in results

    @pytest.mark.asyncio
    async def test_node_failure_propagates(self):
        graph = OrchestrationGraph()

        async def fail(ctx):
            raise RuntimeError("boom")

        graph.add_node("a", AgentNode(name="a", execute=fail, depends_on=[]))
        with pytest.raises(RuntimeError, match="boom"):
            await graph.run({})

    @pytest.mark.asyncio
    async def test_parallel_execution_multiple_nodes(self):
        graph = OrchestrationGraph()
        order = []

        async def track(name):
            async def _exec(ctx):
                order.append(name)
                return name
            return _exec

        graph.add_node("a", AgentNode(name="a", execute=await track("a"), depends_on=[]))
        graph.add_node("b", AgentNode(name="b", execute=await track("b"), depends_on=[]))
        graph.add_node("c", AgentNode(name="c", execute=await track("c"), depends_on=[]))

        results = await graph.run({})
        assert set(results.keys()) == {"a", "b", "c"}

    @pytest.mark.asyncio
    async def test_empty_graph(self):
        graph = OrchestrationGraph()
        results = await graph.run({})
        assert results == {}


class TestAgentNode:
    def test_should_run_no_condition(self):
        node = AgentNode(name="test", execute=AsyncMock())
        assert node.should_run({}) is True

    def test_should_run_condition_true(self):
        node = AgentNode(name="test", execute=AsyncMock(), condition=lambda ctx: True)
        assert node.should_run({}) is True

    def test_should_run_condition_false(self):
        node = AgentNode(name="test", execute=AsyncMock(), condition=lambda ctx: False)
        assert node.should_run({}) is False

    def test_should_run_condition_uses_context(self):
        node = AgentNode(
            name="test", execute=AsyncMock(),
            condition=lambda ctx: ctx.get("quality_mode") == "deep",
        )
        assert node.should_run({"quality_mode": "deep"}) is True
        assert node.should_run({"quality_mode": "fast"}) is False
        assert node.should_run({}) is False
