"""
AgentLoop — 可迭代的 Agent 基类

Claude Code 核心设计模式：Agent 不是"一次出结果就走"，而是拥有工具箱，
可以验证自己的输出、发现问题后自主迭代修正。

使用方式：
    class MyAgent(AgentLoop):
        def build_system_prompt(self, context): ...
        def build_tools(self, context): ...
        def build_tool_handlers(self, context): ...
        def build_initial_messages(self, context): ...
        def validate(self, result): ...
        def parse_result(self, result): ...
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any

from core.llm_client import LLMClient, ProviderRateLimitError, ProviderUnavailableError
from tools.registry import ToolRegistry
from core.prompt_loader import get_prompt_loader

logger = logging.getLogger(__name__)


class AgentLoop(ABC):
    """
    可迭代的 Agent 基类。

    核心循环：
    1. 构建初始消息 + 工具列表
    2. 调用 LLM multi_turn_tool_call（模型可自主选择调用验证工具）
    3. 拿到 submit_result 后，执行 validate() 域校验
    4. 校验不通过 → 注入反馈作为新消息 → 重新调用（最多 max_iterations 轮）
    5. 校验通过 → parse_result() 转为领域模型并返回
    """

    # 子类可覆盖的默认值
    agent_name: str = ""           # 用于 PromptLoader 和模型路由
    max_iterations: int = 3
    max_turns_per_iteration: int = 5
    max_tokens: int = 4000
    temperature: float = 0.8

    @abstractmethod
    def build_system_prompt(self, context: dict) -> str:
        """构建 Agent 的系统 prompt"""

    @abstractmethod
    def build_tools(self, context: dict) -> list[dict]:
        """
        构建工具列表（Anthropic 格式）。
        必须包含一个名为 submit_result 的终止工具，其 input_schema 定义最终输出格式。
        可包含验证/查询等辅助工具。
        """

    @abstractmethod
    def build_tool_handlers(self, context: dict) -> dict[str, Any]:
        """
        返回 {tool_name: handler_fn} 映射。
        handler_fn 签名: (input: dict) -> dict | str
        submit_result 不需要 handler（由框架处理）。
        """

    @abstractmethod
    def build_initial_messages(self, context: dict) -> list[dict]:
        """构建初始消息列表（至少一条 user 消息）"""

    @abstractmethod
    def validate(self, result: dict, context: dict) -> tuple[bool, str]:
        """
        域校验。返回 (is_valid, feedback_message)。
        is_valid=True 时 feedback 被忽略。
        is_valid=False 时 feedback 会被注入为新消息让模型修正。
        """

    @abstractmethod
    def parse_result(self, result: dict, context: dict) -> Any:
        """将 submit_result 的 dict 转为领域模型对象"""

    async def run(
        self,
        client: LLMClient,
        context: dict,
        registry: ToolRegistry | None = None,
    ) -> Any:
        """
        执行 Agent 主循环。

        Args:
            client: LLM 客户端
            context: 上下文数据（request, world, characters 等，由具体 Agent 定义）
            registry: 可选的工具注册中心，提供共享参考工具

        Returns:
            parse_result 返回的领域模型对象
        """
        system_prompt = self.build_system_prompt(context)
        # PromptLoader 覆盖：如果存在版本化 prompt，优先使用
        if self.agent_name:
            loader = get_prompt_loader()
            versioned = loader.get_prompt(self.agent_name)
            if versioned:
                system_prompt = versioned
        tools = self.build_tools(context)
        tool_handlers = self.build_tool_handlers(context)
        messages = self.build_initial_messages(context)

        # 合并注册中心的共享工具
        if registry:
            registered_names = registry.list_tools()
            # 排除已存在的同名工具（Agent 自带的优先）
            existing_names = {t["name"] for t in tools}
            for name in registered_names:
                if name not in existing_names:
                    tools.append(registry.get_tool(name))
                    tool_handlers[name] = registry.get_handler(name)

        last_error = None

        for iteration in range(self.max_iterations):
            if iteration > 0:
                await asyncio.sleep(2 ** iteration)

            try:
                updated_msgs, result = await client.multi_turn_tool_call(
                    system=system_prompt,
                    messages=messages,
                    tools=tools,
                    tool_handlers=tool_handlers,
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                    max_turns=self.max_turns_per_iteration,
                    terminal_tool="submit_result",
                )
                messages = updated_msgs

                if result is None:
                    last_error = RuntimeError("Agent 未调用 submit_result 就结束了对话")
                    # 注入提示让模型知道需要提交结果
                    messages.append({
                        "role": "user",
                        "content": "你还没有调用 submit_result 提交最终结果，请现在提交。",
                    })
                    continue

                # 自动执行验证工具（不消耗 LLM 轮次）
                auto_validation_issues = []
                for vt_name, vt_handler in tool_handlers.items():
                    if vt_name.startswith("validate_"):
                        try:
                            # 从 result 中提取对应字段传给验证工具
                            vt_input = {}
                            if "power" in vt_name and "power_system" in result:
                                vt_input = {"levels": result["power_system"].get("levels", [])}
                            elif "faction" in vt_name and "factions" in result:
                                vt_input = {"factions": result.get("factions", [])}
                            else:
                                continue  # 无法自动匹配输入，跳过
                            vt_result = vt_handler(vt_input)
                            if isinstance(vt_result, dict) and not vt_result.get("valid", True):
                                auto_validation_issues.extend(vt_result.get("issues", []))
                        except Exception as e:
                            logger.debug(f"自动验证 {vt_name} 失败: {e}")

                if auto_validation_issues:
                    logger.info(f"{self.__class__.__name__}: 自动验证发现问题: {auto_validation_issues}")
                    messages.append({
                        "role": "user",
                        "content": (
                            "自动验证发现以下问题，请修正后重新调用 submit_result：\n"
                            + "\n".join(f"- {i}" for i in auto_validation_issues)
                        ),
                    })
                    last_error = ValueError("\n".join(auto_validation_issues))
                    continue

                # 域校验
                is_valid, feedback = self.validate(result, context)
                if is_valid:
                    logger.info(f"{self.__class__.__name__}: 第{iteration+1}轮通过校验")
                    return self.parse_result(result, context)

                # 校验不通过 → 注入反馈
                logger.info(f"{self.__class__.__name__}: 第{iteration+1}轮校验不通过: {feedback[:100]}")
                messages.append({
                    "role": "user",
                    "content": f"你提交的结果存在以下问题，请修正后重新调用 submit_result 提交：\n\n{feedback}",
                })
                last_error = ValueError(feedback)

            except (ProviderRateLimitError, ProviderUnavailableError) as e:
                last_error = e
                continue
            except (KeyError, ValueError, TypeError) as e:
                last_error = e
                continue

        raise RuntimeError(
            f"{self.__class__.__name__} 执行失败（已重试{self.max_iterations}次）：{last_error}"
        )


class SingleShotAgent(AgentLoop):
    """
    向后兼容的单次调用 Agent。
    对于不需要多轮迭代的简单场景，保持原有的单次 tool_call 行为。
    """

    max_iterations: int = 3

    @abstractmethod
    def build_prompt(self, context: dict) -> str:
        """构建 user prompt（单次调用场景）"""

    @abstractmethod
    def get_tool(self) -> tuple[dict, str]:
        """返回 (tool_schema, tool_name)"""

    # 实现 AgentLoop 的抽象方法（委托给简化接口）
    def build_tools(self, context: dict) -> list[dict]:
        tool, _ = self.get_tool()
        return [tool]

    def build_tool_handlers(self, context: dict) -> dict:
        return {}

    def build_initial_messages(self, context: dict) -> list[dict]:
        return [{"role": "user", "content": self.build_prompt(context)}]

    async def run(
        self,
        client: LLMClient,
        context: dict,
        registry: ToolRegistry | None = None,
    ) -> Any:
        """单次调用模式：直接用 client.tool_call()，兼容原有行为"""
        system_prompt = self.build_system_prompt(context)
        # PromptLoader 覆盖
        if self.agent_name:
            loader = get_prompt_loader()
            versioned = loader.get_prompt(self.agent_name)
            if versioned:
                system_prompt = versioned
        prompt = self.build_prompt(context)
        tool, tool_name = self.get_tool()
        last_error = None

        for attempt in range(self.max_iterations):
            if attempt > 0:
                await asyncio.sleep(2 ** attempt)
            try:
                data = await client.tool_call(
                    system_prompt, prompt, tool, tool_name,
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                )
                # 域校验
                is_valid, feedback = self.validate(data, context)
                if is_valid:
                    return self.parse_result(data, context)

                # 校验失败 → 下一次重试
                logger.info(f"{self.__class__.__name__}: 第{attempt+1}次校验不通过: {feedback[:100]}")
                last_error = ValueError(feedback)

            except (KeyError, ValueError) as e:
                last_error = e
                continue
            except (ProviderRateLimitError, ProviderUnavailableError) as e:
                last_error = e
                continue

        raise RuntimeError(
            f"{self.__class__.__name__} 执行失败（已重试{self.max_iterations}次）：{last_error}"
        )


class ThinkingSingleShotAgent(SingleShotAgent):
    """
    带 Extended Thinking 的单次调用 Agent。
    使用 tool_call_with_thinking() 替代 tool_call()，获取模型推理过程。
    thinking_text 可通过 context["_thinking_text"] 传递给 pipeline。
    """

    thinking_budget: int = 10000

    async def run(
        self,
        client: LLMClient,
        context: dict,
        registry: ToolRegistry | None = None,
    ) -> Any:
        """带 Extended Thinking 的单次调用，含域校验重试"""
        system_prompt = self.build_system_prompt(context)
        # PromptLoader 覆盖
        if self.agent_name:
            loader = get_prompt_loader()
            versioned = loader.get_prompt(self.agent_name)
            if versioned:
                system_prompt = versioned
        prompt = self.build_prompt(context)
        tool, tool_name = self.get_tool()
        last_error = None

        for attempt in range(self.max_iterations):
            if attempt > 0:
                await asyncio.sleep(2 ** attempt)
            try:
                data, thinking_text = await client.tool_call_with_thinking(
                    system_prompt, prompt, tool, tool_name,
                    max_tokens=self.max_tokens,
                    thinking_budget=self.thinking_budget,
                )

                # 域校验
                is_valid, feedback = self.validate(data, context)
                if is_valid:
                    result = self.parse_result(data, context)
                    # 将 thinking_text 存入 context 供 pipeline 使用
                    context["_thinking_text"] = thinking_text
                    return result

                logger.info(f"{self.__class__.__name__}: 第{attempt+1}次校验不通过: {feedback[:100]}")
                last_error = ValueError(feedback)

            except (KeyError, ValueError) as e:
                last_error = e
                continue
            except (ProviderRateLimitError, ProviderUnavailableError) as e:
                last_error = e
                continue

        raise RuntimeError(
            f"{self.__class__.__name__} 执行失败（已重试{self.max_iterations}次）：{last_error}"
        )