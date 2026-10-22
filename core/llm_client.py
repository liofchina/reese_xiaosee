"""
LLMClient — 多 Provider 适配层

支持：
- Anthropic（默认，claude-sonnet-4-6 等）
- OpenAI-Compatible API（DeepSeek、通义千问、月之暗面、智谱、豆包等）

环境变量：
  LLM_PROVIDER=anthropic          # 或 openai-compatible
  ANTHROPIC_API_KEY=sk-ant-xxx    # Anthropic 专用
  MODEL=claude-sonnet-4-6         # 可选，覆盖默认模型

  # OpenAI-Compatible 专用：
  LLM_API_KEY=sk-xxx
  LLM_BASE_URL=https://api.deepseek.com/v1
  MODEL=deepseek-chat
"""

import json
import os
import re
import logging
from abc import ABC, abstractmethod
from typing import AsyncIterator, Callable
from core.cache import get_cache
import httpx

logger = logging.getLogger(__name__)

# ── 模型路由配置 ─────────────────────────────────────────────────────────────
# 格式：agent_name → model_id，允许不同 Agent 使用不同模型
# 环境变量 MODEL_ROUTING 为 JSON 字符串，如：
# MODEL_ROUTING={"writer_summary": "claude-haiku-4-5-20251001", "plot_planner": "claude-opus-4-6"}

_model_routing: dict[str, str] = {}

def _load_model_routing():
    global _model_routing
    raw = os.getenv("MODEL_ROUTING", "")
    if raw:
        try:
            _model_routing = json.loads(raw)
            logger.info(f"模型路由已加载: {_model_routing}")
        except json.JSONDecodeError:
            logger.warning(f"MODEL_ROUTING 格式无效: {raw}")

_load_model_routing()


def get_routed_model(agent_name: str, default_model: str) -> str:
    """根据 Agent 名称获取路由模型，未配置则返回默认模型"""
    return _model_routing.get(agent_name, default_model)

# ── 公共异常（runner._retry 捕获这两个） ──────────────────────────────────────

class ProviderRateLimitError(Exception):
    """429 限速，应指数退避重试"""


class ProviderUnavailableError(Exception):
    """500/502/503/529 临时不可用，应指数退避重试"""
    def __init__(self, status_code: int = 0, message: str = ""):
        super().__init__(message or f"Provider unavailable (HTTP {status_code})")
        self.status_code = status_code


class BudgetExceededError(Exception):
    """费用超出预算上限，应立即停止生成"""


# ── 抽象接口 ──────────────────────────────────────────────────────────────────

class LLMClient(ABC):

    def __init__(self):
        self._total_tokens_in = 0
        self._total_tokens_out = 0
        self._total_cost_usd = 0.0
        self._call_count = 0
        self._max_cost = float(os.getenv("MAX_COST_PER_RUN", "10.0"))

    def _track_usage(self, model: str, tokens_in: int, tokens_out: int):
        """记录 token 用量和费用"""
        from core.observability import _estimate_cost
        self._total_tokens_in += tokens_in
        self._total_tokens_out += tokens_out
        cost = _estimate_cost(model, tokens_in, tokens_out)
        self._total_cost_usd += cost
        self._call_count += 1
        # 每5次调用输出一次费用日志
        if self._call_count % 5 == 0:
            logger.info(f"[费用] 累计: ${self._total_cost_usd:.4f} / ${self._max_cost:.2f} "
                       f"(调用{self._call_count}次, {self._total_tokens_in+self._total_tokens_out:,} tokens)")

    def check_budget(self):
        """检查是否超出预算，超出则抛出异常"""
        if self._total_cost_usd >= self._max_cost:
            raise BudgetExceededError(
                f"已超出预算上限！累计费用 ${self._total_cost_usd:.4f} >= 上限 ${self._max_cost:.2f}。"
                f"如需继续，请调高 MAX_COST_PER_RUN 环境变量。"
            )

    def get_cost_summary(self) -> dict:
        """获取当前费用摘要"""
        return {
            "total_cost_usd": round(self._total_cost_usd, 4),
            "max_cost_usd": self._max_cost,
            "total_tokens_in": self._total_tokens_in,
            "total_tokens_out": self._total_tokens_out,
            "total_calls": self._call_count,
            "budget_remaining_usd": round(self._max_cost - self._total_cost_usd, 4),
        }

    @abstractmethod
    async def tool_call(
        self,
        system: str,
        prompt: str,
        tool: dict,
        tool_name: str,
        max_tokens: int = 4000,
        temperature: float = 0.8,
        agent_name: str = "",
    ) -> dict:
        """
        强制调用指定工具，返回工具输入 dict（即结构化结果）。
        tool 使用 Anthropic 格式：{name, description, input_schema}
        """

    @abstractmethod
    async def stream(
        self,
        system: str,
        prompt: str,
        max_tokens: int = 4000,
        temperature: float = 1.0,
        agent_name: str = "",
    ) -> AsyncIterator[str]:
        """流式文本生成，yield 文本片段"""

    @abstractmethod
    async def complete(
        self,
        prompt: str,
        max_tokens: int = 300,
        temperature: float = 0.3,
        agent_name: str = "",
    ) -> str:
        """单次补全，返回完整文本（用于摘要等短文本任务）"""

    async def multi_turn_tool_call(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict],
        tool_handlers: dict[str, Callable],
        max_tokens: int = 4000,
        temperature: float = 0.8,
        max_turns: int = 5,
        terminal_tool: str = "submit_result",
    ) -> tuple[list[dict], dict | None]:
        """
        多轮工具调用循环。模型可自主选择调用哪些工具，直到：
        1. 调用 terminal_tool（如 submit_result）→ 返回其 input 作为最终结果
        2. 达到 max_turns 轮
        3. 模型不再调用任何工具（纯文本回复）

        返回 (完整消息历史, 最终结果 dict 或 None)
        """
        raise NotImplementedError("子类应实现 multi_turn_tool_call")

    async def tool_call_with_thinking(
        self,
        system: str,
        prompt: str,
        tool: dict,
        tool_name: str,
        max_tokens: int = 16000,
        thinking_budget: int = 10000,
    ) -> tuple[dict, str]:
        """
        带 Extended Thinking 的工具调用。返回 (tool_input, thinking_text)。
        默认降级为普通 tool_call()，thinking 返回空字符串。
        """
        result = await self.tool_call(system, prompt, tool, tool_name, max_tokens)
        return result, ""


# ── Anthropic 实现 ────────────────────────────────────────────────────────────

class AnthropicClient(LLMClient):

    def __init__(self):
        super().__init__()
        import anthropic as _anthropic
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key or api_key.startswith("your_"):
            raise ValueError(
                "ANTHROPIC_API_KEY 未配置或仍是占位符，请在 .env 文件中填入有效的 API Key"
            )
        self.client = _anthropic.AsyncAnthropic()
        self.model = os.getenv("MODEL", "claude-sonnet-4-6")

    async def tool_call(
        self,
        system: str,
        prompt: str,
        tool: dict,
        tool_name: str,
        max_tokens: int = 4000,
        temperature: float = 0.8,
        agent_name: str = "",
    ) -> dict:
        import anthropic as _anthropic
        model = get_routed_model(agent_name, self.model) if agent_name else self.model
        # 缓存查询（仅低 temperature 非创作类调用）
        cache = get_cache()
        if cache.enabled and temperature <= 0.5:
            cached = cache.get(system, prompt, tool_name, model)
            if cached is not None:
                return cached
        try:
            msg = await self.client.messages.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system,
                tools=[tool],
                tool_choice={"type": "tool", "name": tool_name},
                messages=[{"role": "user", "content": prompt}],
            )
            # 追踪费用
            if hasattr(msg, 'usage'):
                self._track_usage(model, msg.usage.input_tokens, msg.usage.output_tokens)
            self.check_budget()
            result = msg.content[0].input
            # 写入缓存
            if cache.enabled and temperature <= 0.5:
                cache.put(system, prompt, tool_name, model, result)
            return result
        except _anthropic.RateLimitError as e:
            raise ProviderRateLimitError(str(e)) from e
        except _anthropic.APIStatusError as e:
            if e.status_code in (429, 500, 502, 503, 529):
                raise ProviderUnavailableError(e.status_code, str(e)) from e
            raise

    async def stream(
        self,
        system: str,
        prompt: str,
        max_tokens: int = 4000,
        temperature: float = 1.0,
        agent_name: str = "",
    ) -> AsyncIterator[str]:
        import anthropic as _anthropic
        model = get_routed_model(agent_name, self.model) if agent_name else self.model
        try:
            async with self.client.messages.stream(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system,
                messages=[{"role": "user", "content": prompt}],
            ) as s:
                async for text in s.text_stream:
                    yield text
                # 流结束后获取 usage 并追踪费用
                final_msg = await s.get_final_message()
                if hasattr(final_msg, 'usage'):
                    self._track_usage(model, final_msg.usage.input_tokens, final_msg.usage.output_tokens)
                self.check_budget()
        except _anthropic.RateLimitError as e:
            raise ProviderRateLimitError(str(e)) from e
        except _anthropic.APIStatusError as e:
            if e.status_code in (429, 500, 502, 503, 529):
                raise ProviderUnavailableError(e.status_code, str(e)) from e
            raise

    async def complete(
        self,
        prompt: str,
        max_tokens: int = 300,
        temperature: float = 0.3,
        agent_name: str = "",
    ) -> str:
        import anthropic as _anthropic
        model = get_routed_model(agent_name, self.model) if agent_name else self.model
        # 缓存查询
        cache = get_cache()
        if cache.enabled and temperature <= 0.5:
            cached = cache.get("", prompt, "complete", model)
            if cached is not None:
                return cached.get("text", "")
        try:
            msg = await self.client.messages.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[{"role": "user", "content": prompt}],
            )
            # 追踪费用
            if hasattr(msg, 'usage'):
                self._track_usage(model, msg.usage.input_tokens, msg.usage.output_tokens)
            self.check_budget()
            result = msg.content[0].text.strip()
            if cache.enabled and temperature <= 0.5:
                cache.put("", prompt, "complete", model, {"text": result})
            return result
        except _anthropic.RateLimitError as e:
            raise ProviderRateLimitError(str(e)) from e
        except _anthropic.APIStatusError as e:
            if e.status_code in (429, 500, 502, 503, 529):
                raise ProviderUnavailableError(e.status_code, str(e)) from e
            raise

    async def multi_turn_tool_call(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict],
        tool_handlers: dict[str, Callable],
        max_tokens: int = 4000,
        temperature: float = 0.8,
        max_turns: int = 5,
        terminal_tool: str = "submit_result",
    ) -> tuple[list[dict], dict | None]:
        import anthropic as _anthropic

        msgs = list(messages)
        final_result = None

        for turn in range(max_turns):
            try:
                response = await self.client.messages.create(
                    model=self.model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    system=system,
                    tools=tools,
                    tool_choice={"type": "auto"},
                    messages=msgs,
                )
            except _anthropic.RateLimitError as e:
                raise ProviderRateLimitError(str(e)) from e
            except _anthropic.APIStatusError as e:
                if e.status_code in (429, 500, 502, 503, 529):
                    raise ProviderUnavailableError(e.status_code, str(e)) from e
                raise

            # 将 assistant 回复追加到消息历史
            if isinstance(response, str):
                raise TypeError(
                    f"LLM 返回了非预期的原始文本（可能是 API Key 无效或 SDK 版本问题）：{response[:100]}"
                )
            msgs.append({"role": "assistant", "content": response.content})

            # 检查是否有工具调用
            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if not tool_uses:
                # 纯文本回复，无工具调用 → 结束
                break

            # 处理每个工具调用
            tool_results = []
            for tool_use in tool_uses:
                if tool_use.name == terminal_tool:
                    final_result = tool_use.input
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_use.id,
                        "content": "已收到最终结果",
                    })
                elif tool_use.name in tool_handlers:
                    try:
                        handler = tool_handlers[tool_use.name]
                        result = handler(tool_use.input)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_use.id,
                            "content": json.dumps(result, ensure_ascii=False) if isinstance(result, (dict, list)) else str(result),
                        })
                    except Exception as e:
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_use.id,
                            "content": f"工具执行错误：{e}",
                            "is_error": True,
                        })
                else:
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_use.id,
                        "content": f"未知工具：{tool_use.name}",
                        "is_error": True,
                    })

            msgs.append({"role": "user", "content": tool_results})

            # 如果已拿到 terminal_tool 的结果，退出循环
            if final_result is not None:
                break

        return msgs, final_result

    async def tool_call_with_thinking(
        self,
        system: str,
        prompt: str,
        tool: dict,
        tool_name: str,
        max_tokens: int = 16000,
        thinking_budget: int = 10000,
    ) -> tuple[dict, str]:
        """带 Extended Thinking 的工具调用，返回 (tool_input, thinking_text)"""
        import anthropic as _anthropic

        try:
            msg = await self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                temperature=1.0,  # Extended Thinking 要求 temperature=1
                system=system,
                tools=[tool],
                tool_choice={"type": "tool", "name": tool_name},
                messages=[{"role": "user", "content": prompt}],
                thinking={
                    "type": "enabled",
                    "budget_tokens": thinking_budget,
                },
            )
            # 提取 thinking 和 tool_use
            thinking_text = ""
            tool_input = {}
            for block in msg.content:
                if block.type == "thinking":
                    thinking_text = block.thinking
                elif block.type == "tool_use":
                    tool_input = block.input

            return tool_input, thinking_text

        except _anthropic.RateLimitError as e:
            raise ProviderRateLimitError(str(e)) from e
        except _anthropic.APIStatusError as e:
            if e.status_code in (429, 500, 502, 503, 529):
                raise ProviderUnavailableError(e.status_code, str(e)) from e
            raise


# ── OpenAI-Compatible 实现 ────────────────────────────────────────────────────

class OpenAICompatibleClient(LLMClient):

    def __init__(self):
        super().__init__()
        from openai import AsyncOpenAI
        api_key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY", "")
        base_url = os.getenv("LLM_BASE_URL", "")
        if not api_key:
            raise ValueError("OpenAI-Compatible 模式需要设置 LLM_API_KEY 环境变量")
        if not base_url:
            raise ValueError("OpenAI-Compatible 模式需要设置 LLM_BASE_URL 环境变量")
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.model = os.getenv("MODEL", "")
        if not self.model:
            raise ValueError("OpenAI-Compatible 模式需要设置 MODEL 环境变量")

    def _to_oai_tool(self, tool: dict) -> dict:
        """将 Anthropic tool 格式转换为 OpenAI function 格式"""
        return {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool["input_schema"],
            },
        }

    def _map_error(self, e: Exception):
        """将 OpenAI SDK 异常归一化为公共异常，未匹配的异常原样抛出"""
        from openai import RateLimitError, APIStatusError
        if isinstance(e, RateLimitError):
            raise ProviderRateLimitError(str(e)) from e
        if isinstance(e, APIStatusError):
            if e.status_code in (429, 500, 502, 503, 529):
                raise ProviderUnavailableError(e.status_code, str(e)) from e
        raise

    async def tool_call(
        self,
        system: str,
        prompt: str,
        tool: dict,
        tool_name: str,
        max_tokens: int = 4000,
        temperature: float = 0.8,
        agent_name: str = "",
    ) -> dict:
        oai_tool = self._to_oai_tool(tool)
        model = get_routed_model(agent_name, self.model) if agent_name else self.model
        # 缓存查询
        cache = get_cache()
        if cache.enabled and temperature <= 0.5:
            cached = cache.get(system, prompt, tool_name, model)
            if cached is not None:
                return cached
        try:
            response = await self.client.chat.completions.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                tools=[oai_tool],
                tool_choice={"type": "function", "function": {"name": tool_name}},
            )
            arguments = response.choices[0].message.tool_calls[0].function.arguments
            result = json.loads(arguments)
            if cache.enabled and temperature <= 0.5:
                cache.put(system, prompt, tool_name, model, result)
            return result
        except Exception as e:
            self._map_error(e)

    async def stream(
        self,
        system: str,
        prompt: str,
        max_tokens: int = 4000,
        temperature: float = 1.0,
        agent_name: str = "",
    ) -> AsyncIterator[str]:
        model = get_routed_model(agent_name, self.model) if agent_name else self.model
        try:
            response = await self.client.chat.completions.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                stream=True,
                stream_options={"include_usage": True},
            )
            async for chunk in response:
                # 最后一个 chunk 包含 usage 统计
                if chunk.usage:
                    self._track_usage(
                        model, chunk.usage.prompt_tokens, chunk.usage.completion_tokens
                    )
                    self.check_budget()
                    continue
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as e:
            self._map_error(e)

    async def complete(
        self,
        prompt: str,
        max_tokens: int = 300,
        temperature: float = 0.3,
        agent_name: str = "",
    ) -> str:
        model = get_routed_model(agent_name, self.model) if agent_name else self.model
        # 缓存查询
        cache = get_cache()
        if cache.enabled and temperature <= 0.5:
            cached = cache.get("", prompt, "complete", model)
            if cached is not None:
                return cached.get("text", "")
        try:
            response = await self.client.chat.completions.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[{"role": "user", "content": prompt}],
            )
            result = response.choices[0].message.content.strip()
            if cache.enabled and temperature <= 0.5:
                cache.put("", prompt, "complete", model, {"text": result})
            return result
        except Exception as e:
            self._map_error(e)

    async def multi_turn_tool_call(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict],
        tool_handlers: dict[str, Callable],
        max_tokens: int = 4000,
        temperature: float = 0.8,
        max_turns: int = 5,
        terminal_tool: str = "submit_result",
    ) -> tuple[list[dict], dict | None]:
        """OpenAI 兼容的多轮工具调用循环"""
        oai_tools = [self._to_oai_tool(t) for t in tools]

        # 将 Anthropic 格式消息转为 OpenAI 格式
        oai_msgs = [{"role": "system", "content": system}]
        for m in messages:
            if m["role"] == "user" and isinstance(m["content"], str):
                oai_msgs.append({"role": "user", "content": m["content"]})
            elif m["role"] == "user" and isinstance(m["content"], list):
                # tool_result 格式 → OpenAI tool message
                for item in m["content"]:
                    if isinstance(item, dict) and item.get("type") == "tool_result":
                        oai_msgs.append({
                            "role": "tool",
                            "tool_call_id": item.get("tool_use_id", ""),
                            "content": item.get("content", ""),
                        })
            elif m["role"] == "assistant":
                oai_msgs.append({"role": "assistant", "content": str(m.get("content", ""))})

        final_result = None

        for turn in range(max_turns):
            try:
                response = await self.client.chat.completions.create(
                    model=self.model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    messages=oai_msgs,
                    tools=oai_tools,
                    tool_choice="auto",
                )
            except Exception as e:
                self._map_error(e)

            msg = response.choices[0].message
            oai_msgs.append(msg.model_dump())

            if not msg.tool_calls:
                break

            for tc in msg.tool_calls:
                fn_name = tc.function.name
                fn_args = json.loads(tc.function.arguments)

                if fn_name == terminal_tool:
                    final_result = fn_args
                    oai_msgs.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": "已收到最终结果",
                    })
                elif fn_name in tool_handlers:
                    try:
                        handler = tool_handlers[fn_name]
                        result = handler(fn_args)
                        content = json.dumps(result, ensure_ascii=False) if isinstance(result, (dict, list)) else str(result)
                        oai_msgs.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": content,
                        })
                    except Exception as e:
                        oai_msgs.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": f"工具执行错误：{e}",
                        })
                else:
                    oai_msgs.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": f"未知工具：{fn_name}",
                    })

            if final_result is not None:
                break

        # 将 OAI 消息转回 Anthropic 格式的简化版本
        return messages, final_result


# ── Ollama 本地模型实现 ──────────────────────────────────────────────────────

class OllamaClient(OpenAICompatibleClient):
    """
    Ollama 本地模型客户端，继承 OpenAICompatibleClient 并增加稳定性加固：
    - 连接/读取超时配置（适配模型加载延迟和慢推理）
    - 健康检查 + 模型预加载到 VRAM
    - JSON 修复（处理 Ollama 不完整的工具调用输出）
    - 上下文长度管理（防止 OOM）
    - Ollama 特有错误分类
    """

    def __init__(self):
        super().__init__()
        from openai import AsyncOpenAI
        self.ollama_base = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        self.client = AsyncOpenAI(
            api_key="ollama",  # Ollama 不验证，但 SDK 要求非空
            base_url=f"{self.ollama_base}/v1",
            timeout=httpx.Timeout(
                connect=float(os.getenv("OLLAMA_CONNECT_TIMEOUT", "30")),
                read=float(os.getenv("OLLAMA_READ_TIMEOUT", "300")),
                write=30.0,
                pool=30.0,
            ),
        )
        self.model = os.getenv("MODEL", "qwen3:27b")
        self.context_window = int(os.getenv("OLLAMA_CONTEXT_WINDOW", "32768"))
        self.keepalive_minutes = int(os.getenv("OLLAMA_KEEPALIVE", "30"))
        self._chars_per_token = float(os.getenv("OLLAMA_CHARS_PER_TOKEN", "1.5"))

    # ── 健康检查 & 预加载 ────────────────────────────────────────────────────

    async def health_check(self) -> dict:
        """检查 Ollama 是否运行且模型可用。返回 {"ok": bool, "models": [...], "message": str}"""
        try:
            async with httpx.AsyncClient(timeout=10) as http:
                resp = await http.get(f"{self.ollama_base}/api/tags")
                resp.raise_for_status()
                models = [m["name"] for m in resp.json().get("models", [])]
                # 模糊匹配：qwen3:27b 能匹配 qwen3:27b-q4_K_M
                model_base = self.model.split(":")[0] if ":" in self.model else self.model
                found = any(model_base in m for m in models)
                if found:
                    return {"ok": True, "models": models, "message": ""}
                return {"ok": False, "models": models,
                        "message": f"模型 {self.model} 未找到，请执行: ollama pull {self.model}"}
        except (httpx.HTTPError, OSError) as e:
            return {"ok": False, "models": [],
                    "message": f"Ollama 连接失败 ({self.ollama_base}): {e}"}

    async def preload_model(self):
        """向 Ollama 发送空请求，将模型预加载到 VRAM 并设置 keepalive"""
        try:
            async with httpx.AsyncClient(timeout=60) as http:
                await http.post(
                    f"{self.ollama_base}/api/generate",
                    json={
                        "model": self.model,
                        "prompt": "",
                        "keep_alive": f"{self.keepalive_minutes}m",
                    },
                )
                logger.info(f"Ollama 模型 {self.model} 已预加载，keepalive={self.keepalive_minutes}m")
        except (httpx.HTTPError, OSError) as e:
            logger.warning(f"模型预加载失败（非致命）: {e}")

    # ── JSON 修复 ────────────────────────────────────────────────────────────

    def _repair_json(self, raw: str) -> dict:
        """
        四层 JSON 修复策略，应对 Ollama 可能输出的各种格式问题。
        全部失败则抛出 ValueError（被 AgentLoop 捕获后触发重迭代）。
        """
        # 第1层：直接解析
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            pass

        # 第1.5层：去掉 JSON 后多余文字（如 "}\n\n以上是..." 或 "}\nHere is..."）
        stripped = raw.strip()
        # 找到最后一个 } 或 ] 的位置，截掉后面的内容
        last_brace = max(stripped.rfind('}'), stripped.rfind(']'))
        if last_brace > 0 and last_brace < len(stripped) - 1:
            try:
                return json.loads(stripped[:last_brace + 1])
            except (json.JSONDecodeError, TypeError):
                pass

        # 第2层：去除 markdown 代码围栏
        cleaned = re.sub(r"```(?:json)?\s*\n?", "", raw).strip()
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3].strip()
        try:
            return json.loads(cleaned)
        except (json.JSONDecodeError, TypeError):
            pass

        # 第3层：闭合未关闭的括号（处理截断 JSON）
        text = cleaned or raw.strip()
        # 去掉尾部不完整的值（可能是截断的字符串或数字）
        text = re.sub(r',\s*"[^"]*$', "", text)  # 去掉最后一个不完整的键
        text = re.sub(r',\s*$', "", text)  # 去掉尾部逗号
        # 计算需要闭合的括号
        opens = []
        in_string = False
        escape = False
        for ch in text:
            if escape:
                escape = False
                continue
            if ch == '\\':
                escape = True
                continue
            if ch == '"' and not escape:
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch in '{[':
                opens.append(ch)
            elif ch == '}' and opens and opens[-1] == '{':
                opens.pop()
            elif ch == ']' and opens and opens[-1] == '[':
                opens.pop()
        # 补全缺少的闭合括号
        closing = ""
        for bracket in reversed(opens):
            closing += ']' if bracket == '[' else '}'
        if closing:
            try:
                return json.loads(text + closing)
            except (json.JSONDecodeError, TypeError):
                pass

        # 第4层：正则提取第一个 {...}
        match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', raw, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except (json.JSONDecodeError, TypeError):
                pass

        raise ValueError(f"无法修复 JSON: {raw[:200]}...")

    # ── 上下文长度管理 ────────────────────────────────────────────────────────

    def _estimate_tokens(self, text: str) -> int:
        """粗略 token 估算：中文 ~1.5 tok/字，ASCII ~0.25 tok/字符"""
        chinese = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        ascii_chars = len(text) - chinese
        return int(chinese * self._chars_per_token + ascii_chars * 0.25)

    def _truncate_for_context(
        self, system: str, prompt: str, max_tokens: int
    ) -> tuple[str, str]:
        """确保 system + prompt + max_tokens 不超过 context_window"""
        budget = self.context_window - 512  # 消息格式开销
        used = self._estimate_tokens(system) + self._estimate_tokens(prompt) + max_tokens
        if used <= budget:
            return system, prompt

        excess_tokens = used - budget
        excess_chars = int(excess_tokens / self._chars_per_token)
        logger.warning(
            f"上下文超限 {used}/{budget} tokens，将截断 prompt（约 {excess_chars} 字符）"
        )

        # 中间截断：保留开头 70%（章节大纲/指令）+ 结尾 30%（上章摘要）
        if excess_chars < len(prompt):
            mid = len(prompt) // 2
            half_cut = excess_chars // 2
            prompt = (
                prompt[:mid - half_cut]
                + "\n\n[...中间内容因上下文限制已省略...]\n\n"
                + prompt[mid + half_cut:]
            )
        else:
            # prompt 都不够截，极端情况只保留前 budget 对应的字符
            keep_chars = int((budget - max_tokens) / self._chars_per_token)
            prompt = prompt[:max(keep_chars, 500)] + "\n[...内容已截断...]"

        return system, prompt

    # ── 方法覆写 ─────────────────────────────────────────────────────────────

    async def tool_call(
        self,
        system: str,
        prompt: str,
        tool: dict,
        tool_name: str,
        max_tokens: int = 4000,
        temperature: float = 0.8,
        agent_name: str = "",
    ) -> dict:
        system, prompt = self._truncate_for_context(system, prompt, max_tokens)
        oai_tool = self._to_oai_tool(tool)
        model = get_routed_model(agent_name, self.model) if agent_name else self.model
        # 缓存查询
        cache = get_cache()
        if cache.enabled and temperature <= 0.5:
            cached = cache.get(system, prompt, tool_name, model)
            if cached is not None:
                return cached
        try:
            response = await self.client.chat.completions.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                tools=[oai_tool],
                tool_choice={"type": "function", "function": {"name": tool_name}},
            )
            arguments = response.choices[0].message.tool_calls[0].function.arguments
            result = self._repair_json(arguments)
            if cache.enabled and temperature <= 0.5:
                cache.put(system, prompt, tool_name, model, result)
            return result
        except Exception as e:
            self._map_error(e)

    async def stream(
        self,
        system: str,
        prompt: str,
        max_tokens: int = 4000,
        temperature: float = 1.0,
        agent_name: str = "",
    ) -> AsyncIterator[str]:
        system, prompt = self._truncate_for_context(system, prompt, max_tokens)
        model = get_routed_model(agent_name, self.model) if agent_name else self.model
        try:
            response = await self.client.chat.completions.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                stream=True,
            )
            # Ollama 不支持 stream_options，用字符计数估算 token
            output_chars = 0
            async for chunk in response:
                if chunk.choices and chunk.choices[0].delta.content:
                    text = chunk.choices[0].delta.content
                    output_chars += len(text)
                    yield text
            # 流结束后用估算追踪费用
            est_input = self._estimate_tokens(system + prompt)
            est_output = self._estimate_tokens("x" * output_chars)
            self._track_usage(model, est_input, est_output)
        except Exception as e:
            self._map_error(e)

    async def complete(
        self,
        prompt: str,
        max_tokens: int = 300,
        temperature: float = 0.3,
        agent_name: str = "",
    ) -> str:
        _, prompt = self._truncate_for_context("", prompt, max_tokens)
        model = get_routed_model(agent_name, self.model) if agent_name else self.model
        cache = get_cache()
        if cache.enabled and temperature <= 0.5:
            cached = cache.get("", prompt, "complete", model)
            if cached is not None:
                return cached.get("text", "")
        try:
            response = await self.client.chat.completions.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[{"role": "user", "content": prompt}],
            )
            result = response.choices[0].message.content.strip()
            if cache.enabled and temperature <= 0.5:
                cache.put("", prompt, "complete", model, {"text": result})
            return result
        except Exception as e:
            self._map_error(e)

    async def multi_turn_tool_call(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict],
        tool_handlers: dict[str, Callable],
        max_tokens: int = 4000,
        temperature: float = 0.8,
        max_turns: int = 5,
        terminal_tool: str = "submit_result",
    ) -> tuple[list[dict], dict | None]:
        """Ollama 多轮工具调用，增加 JSON 修复"""
        oai_tools = [self._to_oai_tool(t) for t in tools]

        # 将 Anthropic 格式消息转为 OpenAI 格式
        oai_msgs = [{"role": "system", "content": system}]
        for m in messages:
            if m["role"] == "user" and isinstance(m["content"], str):
                oai_msgs.append({"role": "user", "content": m["content"]})
            elif m["role"] == "user" and isinstance(m["content"], list):
                for item in m["content"]:
                    if isinstance(item, dict) and item.get("type") == "tool_result":
                        oai_msgs.append({
                            "role": "tool",
                            "tool_call_id": item.get("tool_use_id", ""),
                            "content": item.get("content", ""),
                        })
            elif m["role"] == "assistant":
                oai_msgs.append({"role": "assistant", "content": str(m.get("content", ""))})

        final_result = None

        for turn in range(max_turns):
            try:
                response = await self.client.chat.completions.create(
                    model=self.model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    messages=oai_msgs,
                    tools=oai_tools,
                    tool_choice="auto",
                )
            except Exception as e:
                self._map_error(e)

            msg = response.choices[0].message
            oai_msgs.append(msg.model_dump())

            if not msg.tool_calls:
                break

            for tc in msg.tool_calls:
                fn_name = tc.function.name
                fn_args = self._repair_json(tc.function.arguments)  # JSON 修复

                if fn_name == terminal_tool:
                    final_result = fn_args
                    oai_msgs.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": "已收到最终结果",
                    })
                elif fn_name in tool_handlers:
                    try:
                        handler = tool_handlers[fn_name]
                        result = handler(fn_args)
                        content = json.dumps(result, ensure_ascii=False) if isinstance(result, (dict, list)) else str(result)
                        oai_msgs.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": content,
                        })
                    except Exception as e:
                        oai_msgs.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": f"工具执行错误：{e}",
                        })
                else:
                    oai_msgs.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": f"未知工具：{fn_name}",
                    })

            if final_result is not None:
                break

        return messages, final_result

    def _map_error(self, e: Exception):
        """Ollama 特有错误分类"""
        err_str = str(e).lower()
        # OOM
        if "out of memory" in err_str or "oom" in err_str:
            raise ProviderUnavailableError(503, f"Ollama OOM: {e}") from e
        # 模型未加载
        if "model" in err_str and ("not found" in err_str or "loading" in err_str):
            raise ProviderUnavailableError(503, f"Ollama 模型未就绪: {e}") from e
        # 连接类错误
        if isinstance(e, (ConnectionError, OSError, httpx.ConnectError, httpx.ReadTimeout)):
            raise ConnectionError(f"Ollama 连接异常: {e}") from e
        # 其余交给父类处理
        super()._map_error(e)


# ── 工厂函数 ──────────────────────────────────────────────────────────────────

def validate_provider_config():
    """启动时校验 LLM 提供商配置，fail-fast（建议11）"""
    provider = os.getenv("LLM_PROVIDER", "anthropic").lower()
    if provider == "anthropic":
        key = os.getenv("ANTHROPIC_API_KEY", "")
        if not key:
            raise EnvironmentError(
                "ANTHROPIC_API_KEY 未设置。请在 .env 文件中配置，或执行: "
                "cp resources/.env.example .env && 编辑 .env"
            )
    elif provider in ("openai-compatible", "openai_compatible", "openai"):
        if not (os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")):
            raise EnvironmentError("OpenAI-Compatible 模式需要设置 LLM_API_KEY 环境变量")
        if not os.getenv("LLM_BASE_URL"):
            raise EnvironmentError("OpenAI-Compatible 模式需要设置 LLM_BASE_URL 环境变量")
        if not os.getenv("MODEL"):
            raise EnvironmentError("OpenAI-Compatible 模式需要设置 MODEL 环境变量")
    elif provider == "ollama":
        pass  # Ollama 有运行时健康检查
    else:
        raise EnvironmentError(
            f"未知的 LLM_PROVIDER='{provider}'，支持：anthropic | ollama | openai-compatible"
        )


def create_client() -> LLMClient:
    """根据 LLM_PROVIDER 环境变量创建对应客户端（默认 anthropic）"""
    provider = os.getenv("LLM_PROVIDER", "anthropic").lower()
    if provider == "anthropic":
        return AnthropicClient()
    elif provider == "ollama":
        logger.warning("Ollama 支持已暂时禁用（稳定性不足）。如需使用请确认本地 Ollama 服务正常。")
        return OllamaClient()
    elif provider in ("openai-compatible", "openai_compatible", "openai"):
        return OpenAICompatibleClient()
    else:
        raise ValueError(
            f"未知的 LLM_PROVIDER='{provider}'，支持：anthropic | openai-compatible"
        )
