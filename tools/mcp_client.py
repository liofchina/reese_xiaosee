"""
MCP 客户端 — 连接外部 MCP 工具服务器

支持通过 Model Context Protocol 接入外部工具（如小说素材库、写作风格分析器等），
并自动注册到 ToolRegistry。

配置方式（.env）：
  MCP_SERVERS={"novel_research": {"command": "npx", "args": ["-y", "novel-research-server"]}}
"""

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 安全：MCP 服务器允许执行的命令白名单
ALLOWED_MCP_COMMANDS = {"npx", "node", "python", "python3", "uvx"}


class MCPToolBridge:
    """
    MCP 工具桥接器：将 MCP 服务器的工具转为 ToolRegistry 可用的格式。

    简化实现：通过 subprocess 启动 MCP 服务器，通过 stdin/stdout JSON-RPC 通信。
    """

    def __init__(self, server_name: str, command: str, args: list[str]):
        self.server_name = server_name
        self.command = command
        self.args = args
        self.process: asyncio.subprocess.Process | None = None
        self._request_id = 0
        self._tools: dict[str, dict] = {}

    async def connect(self) -> bool:
        """启动 MCP 服务器并执行初始化握手"""
        # 安全校验：只允许白名单内的命令
        cmd_base = Path(self.command).name if "/" in self.command or "\\" in self.command else self.command
        if cmd_base not in ALLOWED_MCP_COMMANDS:
            logger.warning(
                f"MCP 服务器 '{self.server_name}' 的命令 '{self.command}' "
                f"不在白名单 {ALLOWED_MCP_COMMANDS} 中，拒绝启动"
            )
            return False

        try:
            self.process = await asyncio.create_subprocess_exec(
                self.command, *self.args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            # 发送初始化请求
            response = await self._send_request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "reese-ag", "version": "1.0.0"},
            })
            if response and "result" in response:
                logger.info(f"MCP 服务器 '{self.server_name}' 已连接")
                # 发送 initialized 通知
                await self._send_notification("notifications/initialized", {})
                return True
            return False
        except Exception as e:
            logger.warning(f"MCP 服务器 '{self.server_name}' 连接失败: {e}")
            return False

    async def discover_tools(self) -> list[dict]:
        """发现 MCP 服务器提供的工具"""
        response = await self._send_request("tools/list", {})
        if response and "result" in response:
            tools = response["result"].get("tools", [])
            for tool in tools:
                self._tools[tool["name"]] = tool
            logger.info(f"从 '{self.server_name}' 发现 {len(tools)} 个工具")
            return tools
        return []

    async def call_tool(self, name: str, arguments: dict) -> Any:
        """调用 MCP 工具"""
        response = await self._send_request("tools/call", {
            "name": name,
            "arguments": arguments,
        })
        if response and "result" in response:
            content = response["result"].get("content", [])
            # 提取文本内容
            texts = [c["text"] for c in content if c.get("type") == "text"]
            return "\n".join(texts) if texts else str(content)
        return None

    async def disconnect(self):
        """关闭 MCP 服务器"""
        if self.process:
            try:
                self.process.stdin.close()
                self.process.terminate()
                await asyncio.wait_for(self.process.wait(), timeout=5)
            except Exception:
                self.process.kill()
            self.process = None

    async def _send_request(self, method: str, params: dict) -> dict | None:
        """发送 JSON-RPC 请求"""
        if not self.process or not self.process.stdin:
            return None

        self._request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params,
        }

        try:
            data = json.dumps(request) + "\n"
            self.process.stdin.write(data.encode())
            await self.process.stdin.drain()

            line = await asyncio.wait_for(self.process.stdout.readline(), timeout=30)
            if line:
                return json.loads(line.decode())
        except Exception as e:
            logger.warning(f"MCP 请求失败 ({method}): {e}")
        return None

    async def _send_notification(self, method: str, params: dict):
        """发送 JSON-RPC 通知（不期望响应）"""
        if not self.process or not self.process.stdin:
            return

        notification = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        try:
            data = json.dumps(notification) + "\n"
            self.process.stdin.write(data.encode())
            await self.process.stdin.drain()
        except Exception:
            pass


def _make_mcp_tool_handler(bridge: MCPToolBridge, tool_name: str):
    """创建 MCP 工具的同步 handler（内部用 asyncio.run）"""
    def handler(input_data: dict) -> str:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # 在已有事件循环中创建 task
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                result = pool.submit(
                    asyncio.run, bridge.call_tool(tool_name, input_data)
                ).result(timeout=30)
            return result or "工具调用无返回"
        else:
            result = asyncio.run(bridge.call_tool(tool_name, input_data))
            return result or "工具调用无返回"
    return handler


async def setup_mcp_tools(registry) -> list[MCPToolBridge]:
    """
    从环境变量加载 MCP 服务器配置，连接并注册工具。

    .env 配置示例：
    MCP_SERVERS={"novel_research": {"command": "npx", "args": ["-y", "novel-research-server"]}}

    返回已连接的 bridge 列表（调用方负责在退出时 disconnect）。
    """
    config_str = os.getenv("MCP_SERVERS", "")
    if not config_str:
        return []

    try:
        config = json.loads(config_str)
    except json.JSONDecodeError:
        logger.warning("MCP_SERVERS 配置格式无效，跳过 MCP 初始化")
        return []

    bridges = []

    for server_name, server_config in config.items():
        command = server_config.get("command", "")
        args = server_config.get("args", [])

        if not command:
            logger.warning(f"MCP 服务器 '{server_name}' 缺少 command 配置")
            continue

        bridge = MCPToolBridge(server_name, command, args)
        if await bridge.connect():
            tools = await bridge.discover_tools()
            for tool in tools:
                # 转换 MCP 工具 schema 为 Anthropic 格式并注册
                registry.register(
                    name=tool["name"],
                    description=tool.get("description", ""),
                    input_schema=tool.get("inputSchema", {"type": "object", "properties": {}}),
                    handler=_make_mcp_tool_handler(bridge, tool["name"]),
                    source=f"mcp:{server_name}",
                )
            bridges.append(bridge)
        else:
            logger.warning(f"MCP 服务器 '{server_name}' 连接失败，跳过")

    return bridges
