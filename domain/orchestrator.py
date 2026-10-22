"""
OrchestrationGraph — DAG 编排引擎

Claude Code 核心理念：从硬编码线性流水线升级为可配置的 Agent 编排图。
支持：
- 顺序执行（默认，复现当前行为）
- 并行执行（无依赖的 Agent 可并发）
- 条件分支（如 deep 模式才执行 ConsistencyChecker）
- Agent 间消息传递
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

logger = logging.getLogger(__name__)


@dataclass
class AgentNode:
    """编排图中的一个 Agent 节点"""
    name: str
    execute: Callable[..., Awaitable[Any]]  # async 执行函数
    depends_on: list[str] = field(default_factory=list)
    condition: Callable[[dict], bool] | None = None  # 条件函数，返回 False 则跳过

    def should_run(self, context: dict) -> bool:
        """判断此节点是否应该执行"""
        if self.condition is None:
            return True
        return self.condition(context)


class OrchestrationGraph:
    """
    DAG 编排图引擎。

    使用方式：
        graph = OrchestrationGraph()
        graph.add_node("world", AgentNode(
            name="world",
            execute=build_world_fn,
            depends_on=[],
        ))
        graph.add_node("characters", AgentNode(
            name="characters",
            execute=design_characters_fn,
            depends_on=["world"],
        ))

        results = await graph.run(initial_context)
    """

    def __init__(self):
        self._nodes: dict[str, AgentNode] = {}
        self._order: list[str] = []  # 拓扑排序后的执行顺序

    def add_node(self, name: str, node: AgentNode) -> "OrchestrationGraph":
        """添加节点（链式调用）"""
        self._nodes[name] = node
        self._order = []  # 清除缓存的排序
        return self

    def _topological_sort(self) -> list[str]:
        """拓扑排序，确定执行顺序"""
        if self._order:
            return self._order

        visited = set()
        temp_mark = set()
        order = []

        def visit(name):
            if name in temp_mark:
                raise ValueError(f"检测到循环依赖: {name}")
            if name in visited:
                return
            temp_mark.add(name)
            node = self._nodes[name]
            for dep in node.depends_on:
                if dep in self._nodes:
                    visit(dep)
            temp_mark.remove(name)
            visited.add(name)
            order.append(name)

        for name in self._nodes:
            visit(name)

        self._order = order
        return order

    def _find_parallel_groups(self) -> list[list[str]]:
        """
        将拓扑排序分组：同一组内的节点可以并行执行。
        """
        order = self._topological_sort()
        groups = []
        completed = set()

        remaining = list(order)
        while remaining:
            # 找出所有依赖已满足的节点
            ready = [
                n for n in remaining
                if all(d in completed for d in self._nodes[n].depends_on)
            ]
            if not ready:
                raise RuntimeError("无法调度剩余节点，可能存在未注册的依赖")

            groups.append(ready)
            completed.update(ready)
            remaining = [n for n in remaining if n not in completed]

        return groups

    async def run(
        self,
        context: dict,
        on_status: Callable[[str, str], Awaitable[None]] | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> dict[str, Any]:
        """
        执行编排图。

        Args:
            context: 共享上下文（各节点可读写）
            on_status: 状态回调 async (node_name, message) -> None
            cancel_event: 取消事件

        Returns:
            {node_name: result} 映射
        """
        groups = self._find_parallel_groups()
        results: dict[str, Any] = {}

        for group in groups:
            if cancel_event and cancel_event.is_set():
                break

            # 过滤掉条件不满足的节点
            runnable = [
                name for name in group
                if self._nodes[name].should_run(context)
            ]

            if len(runnable) == 1:
                # 单节点，直接执行
                name = runnable[0]
                if on_status:
                    await on_status(name, f"正在执行 {name}...")

                result = await self._nodes[name].execute(context)
                results[name] = result
                context[f"result_{name}"] = result

            elif len(runnable) > 1:
                # 多节点，并行执行
                if on_status:
                    names_str = ", ".join(runnable)
                    await on_status("parallel", f"并行执行: {names_str}")

                tasks = {
                    name: asyncio.create_task(self._nodes[name].execute(context))
                    for name in runnable
                }
                for name, task in tasks.items():
                    try:
                        result = await task
                        results[name] = result
                        context[f"result_{name}"] = result
                    except Exception as e:
                        logger.error(f"节点 {name} 执行失败: {e}")
                        raise

        return results


def build_default_graph(
    client=None,
    request=None,
) -> OrchestrationGraph:
    """
    构建默认编排图，表达当前的六阶段流水线依赖关系。

    当提供 client 和 request 时，绑定真实的 Agent 执行函数。
    否则返回骨架图（占位 lambda）。

    注意：ChapterOutliner 和 Writer 涉及循环迭代（逐卷/逐章），
    目前以单节点表示。未来可扩展为子图或循环节点。
    """
    graph = OrchestrationGraph()

    if client and request:
        # 绑定真实 Agent 执行函数
        from agents.world_builder import build_world
        from agents.character_designer import design_characters
        from agents.plot_planner import plan_plot
        from agents.chapter_outliner import outline_volume

        async def _exec_world(ctx):
            world = await build_world(client, request)
            ctx["world"] = world
            return world

        async def _exec_characters(ctx):
            chars, antags = await design_characters(client, request, ctx["world"])
            ctx["characters"] = chars
            ctx["antagonists"] = antags
            return chars, antags

        async def _exec_plot(ctx):
            title, pf, vols = await plan_plot(
                client, request, ctx["world"], ctx["characters"], ctx["antagonists"]
            )
            ctx["title"] = title
            ctx["plot_framework"] = pf
            ctx["volumes"] = vols
            return title, pf, vols

        async def _exec_outlines(ctx):
            volumes = ctx["volumes"]
            global_start = 1
            all_outlines = []
            for vol in volumes:
                prev_ending = volumes[vol.volume_num - 2].ending_hook if vol.volume_num > 1 else ""
                outlines = await outline_volume(
                    client, request, ctx["world"], ctx["characters"],
                    ctx["antagonists"], vol, prev_ending, global_start,
                )
                vol.chapters = outlines
                all_outlines.extend(outlines)
                global_start += len(outlines)
            ctx["all_chapter_outlines"] = all_outlines
            return all_outlines

        graph.add_node("world_builder", AgentNode(
            name="world_builder",
            execute=_exec_world,
            depends_on=[],
        ))
        graph.add_node("character_designer", AgentNode(
            name="character_designer",
            execute=_exec_characters,
            depends_on=["world_builder"],
        ))
        graph.add_node("plot_planner", AgentNode(
            name="plot_planner",
            execute=_exec_plot,
            depends_on=["character_designer"],
        ))
        graph.add_node("chapter_outliner", AgentNode(
            name="chapter_outliner",
            execute=_exec_outlines,
            depends_on=["plot_planner"],
        ))
    else:
        # 骨架模式（用于依赖分析和可视化）
        graph.add_node("world_builder", AgentNode(
            name="world_builder",
            execute=lambda ctx: None,
            depends_on=[],
        ))
        graph.add_node("character_designer", AgentNode(
            name="character_designer",
            execute=lambda ctx: None,
            depends_on=["world_builder"],
        ))
        graph.add_node("plot_planner", AgentNode(
            name="plot_planner",
            execute=lambda ctx: None,
            depends_on=["character_designer"],
        ))
        graph.add_node("chapter_outliner", AgentNode(
            name="chapter_outliner",
            execute=lambda ctx: None,
            depends_on=["plot_planner"],
        ))

    # Writer 和 ConsistencyChecker 涉及流式输出和逐章循环，
    # 暂不纳入图执行，由 pipeline.py 直接处理。
    graph.add_node("writer", AgentNode(
        name="writer",
        execute=lambda ctx: None,
        depends_on=["chapter_outliner"],
    ))
    graph.add_node("consistency_checker", AgentNode(
        name="consistency_checker",
        execute=lambda ctx: None,
        depends_on=["writer"],
        condition=lambda ctx: ctx.get("quality_mode") == "deep",
    ))

    return graph
