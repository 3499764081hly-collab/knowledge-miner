"""MCP Server 模块 - 核心集成接口"""

from __future__ import annotations

import json
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    CallToolResult,
    ListToolsResult,
    TextContent,
    Tool,
)

from knowledge_miner.config import get_config
from knowledge_miner.miner import mine_knowledge
from knowledge_miner.output.ai_knowledge_base import extract_agent_view
from knowledge_miner.output.json_writer import JsonWriter

# 创建 MCP Server 实例
server = Server("knowledge-miner")


@server.list_tools()
async def list_tools() -> ListToolsResult:
    """列出所有可用工具"""
    return ListToolsResult(
        tools=[
            Tool(
                name="mine_knowledge",
                description="从 AI agent 聊天记录中沉淀知识库。可指定时间范围和数据源。",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "days": {
                            "type": "integer",
                            "description": "分析最近 N 天的会话（默认 7）",
                            "default": 7,
                            "minimum": 1,
                            "maximum": 365,
                        },
                        "source": {
                            "type": "string",
                            "description": (
                                "数据源：claude（Claude Code）、hermes（飞书 Hermes）、"
                                "all（全部）"
                            ),
                            "enum": ["claude", "hermes", "all"],
                            "default": "all",
                        },
                        "dry_run": {
                            "type": "boolean",
                            "description": "只预览将写入的内容，不修改知识库文件",
                            "default": False,
                        },
                        "confirm_write": {
                            "type": "boolean",
                            "description": "确认写入知识库文件；未提供 true 时只返回预览",
                            "default": False,
                        },
                    },
                    "additionalProperties": False,
                },
            ),
            Tool(
                name="get_knowledge",
                description="读取已沉淀的知识库内容。可按部分读取。",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "section": {
                            "type": "string",
                            "description": (
                                "读取特定部分：pitfalls（踩坑）、thinking（思维）、"
                                "workflows（工作流）、communication（沟通风格）、all（全部）"
                            ),
                            "enum": ["pitfalls", "thinking", "workflows", "communication", "all"],
                            "default": "all",
                        },
                    },
                    "additionalProperties": False,
                },
            ),
            Tool(
                name="get_stats",
                description="查看知识库的统计信息，包括数据源、会话数、消息数等。",
                inputSchema={
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            ),
        ]
    )


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> CallToolResult:
    """调用工具"""
    try:
        if name == "mine_knowledge":
            return await _handle_mine_knowledge(arguments)
        elif name == "get_knowledge":
            return await _handle_get_knowledge(arguments)
        elif name == "get_stats":
            return await _handle_get_stats(arguments)
        else:
            return CallToolResult(
                content=[TextContent(type="text", text=f"未知工具: {name}")],
                isError=True,
            )
    except Exception as e:
        return CallToolResult(
            content=[TextContent(type="text", text=f"错误: {str(e)}")],
            isError=True,
        )


async def _handle_mine_knowledge(arguments: dict[str, Any]) -> CallToolResult:
    """处理知识沉淀请求"""
    config = get_config()

    parsed = _parse_mine_arguments(arguments)
    if isinstance(parsed, CallToolResult):
        return parsed
    days, source, dry_run, confirm_write = parsed

    result = mine_knowledge(days=days, source=source, config=config)

    if not result.messages or not result.knowledge_base:
        return CallToolResult(
            content=[
                TextContent(
                    type="text",
                    text=f"最近 {days} 天内没有找到任何消息。请检查数据源配置。",
                )
            ],
        )

    if dry_run or not confirm_write:
        output = json.dumps(result.preview, indent=2, ensure_ascii=False, default=str)
        reason = (
            "dry-run 预览，未写入任何文件"
            if dry_run
            else "未提供 confirm_write=true，已返回预览且未写入任何文件"
        )
        return CallToolResult(
            content=[
                TextContent(
                    type="text",
                    text=f"{reason}：\n{output}",
                )
            ],
        )

    writer = JsonWriter(result.output_path)
    writer.write(result.knowledge_base)
    backup_line = (
        f"\n🧷 写入前备份: {writer.last_backup_path}"
        if writer.last_backup_path
        else ""
    )

    pitfalls = result.knowledge_base.pitfalls.get("items", [])
    patterns = result.knowledge_base.thinking_patterns.get("items", [])
    workflows = result.knowledge_base.workflows.get("items", [])

    summary = (
        f"✅ 知识沉淀完成！\n\n"
        f"📊 分析结果:\n"
        f"  - 数据源: {', '.join(result.sources)}\n"
        f"  - 时间范围: 最近 {days} 天 "
        f"({result.date_range[0].strftime('%Y-%m-%d')} ~ "
        f"{result.date_range[1].strftime('%Y-%m-%d')})\n"
        f"  - 消息数: {len(result.messages)}\n"
        f"  - 会话数: {result.session_count}\n\n"
        f"📝 沉淀内容:\n"
        f"  - ⚠️ 踩过的坑: {len(pitfalls)} 条\n"
        f"  - 🧠 思维方式: {len(patterns)} 条\n"
        f"  - 🔄 工作流: {len(workflows)} 条\n\n"
        f"📁 知识库已保存到: {result.output_path}"
        f"{backup_line}"
    )

    return CallToolResult(
        content=[TextContent(type="text", text=summary)],
    )


async def _handle_get_knowledge(arguments: dict[str, Any]) -> CallToolResult:
    """处理知识库读取请求"""
    config = get_config()
    section = arguments.get("section", "all")
    if not isinstance(section, str) or section not in {
        "pitfalls",
        "thinking",
        "workflows",
        "communication",
        "all",
    }:
        return _tool_error(
            "参数 section 必须是 pitfalls/thinking/workflows/communication/all 之一"
        )

    writer = JsonWriter(config.output_path)
    data = writer.read()

    if not data:
        return CallToolResult(
            content=[
                TextContent(
                    type="text",
                    text="知识库不存在。请先运行 mine_knowledge 工具沉淀知识。",
                )
            ],
        )

    agent_view = extract_agent_view(data)

    # 根据 section 过滤
    if section != "all":
        section_map = {
            "pitfalls": "pitfalls",
            "thinking": "thinking_patterns",
            "workflows": "workflows",
            "communication": "communication_style",
        }
        key = section_map.get(section, section)
        if key in agent_view:
            result = {key: agent_view[key], "metadata": agent_view.get("metadata", {})}
        else:
            result = agent_view
    else:
        result = agent_view

    # 格式化输出
    output = json.dumps(result, indent=2, ensure_ascii=False, default=str)

    return CallToolResult(
        content=[TextContent(type="text", text=output)],
    )


async def _handle_get_stats(arguments: dict[str, Any]) -> CallToolResult:
    """处理统计信息请求"""
    if arguments:
        return _tool_error("get_stats 不接受任何参数")

    config = get_config()

    writer = JsonWriter(config.output_path)
    data = writer.read()

    if not data:
        return CallToolResult(
            content=[
                TextContent(
                    type="text",
                    text="知识库不存在。请先运行 mine_knowledge 工具沉淀知识。",
                )
            ],
        )

    agent_view = extract_agent_view(data)
    meta = agent_view.get("metadata", {})
    pitfalls = agent_view.get("pitfalls", {}).get("items", [])
    patterns = agent_view.get("thinking_patterns", {}).get("items", [])
    workflows = agent_view.get("workflows", {}).get("items", [])

    stats = {
        "version": meta.get("version", "unknown"),
        "generated_at": meta.get("generated_at", "unknown"),
        "sources": meta.get("sources", []),
        "total_sessions": meta.get("total_sessions", 0),
        "total_messages": meta.get("total_messages", 0),
        "date_range": meta.get("date_range", {}),
        "counts": {
            "pitfalls": len(pitfalls),
            "thinking_patterns": len(patterns),
            "workflows": len(workflows),
        },
    }

    output = json.dumps(stats, indent=2, ensure_ascii=False, default=str)

    return CallToolResult(
        content=[TextContent(type="text", text=output)],
    )


async def run_server(transport: str = "stdio") -> None:
    """运行 MCP Server"""
    if transport == "stdio":
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )
    else:
        raise ValueError(f"不支持的传输方式: {transport}")


def _parse_mine_arguments(
    arguments: dict[str, Any],
) -> tuple[int, str, bool, bool] | CallToolResult:
    """Validate mine_knowledge arguments at runtime, not only via JSON schema."""
    allowed_keys = {"days", "source", "dry_run", "confirm_write"}
    unknown_keys = set(arguments) - allowed_keys
    if unknown_keys:
        return _tool_error(f"未知参数: {', '.join(sorted(unknown_keys))}")

    days = arguments.get("days", 7)
    if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 365:
        return _tool_error("参数 days 必须是 1 到 365 之间的整数")

    source = arguments.get("source", "all")
    if not isinstance(source, str) or source not in {"claude", "hermes", "all"}:
        return _tool_error("参数 source 必须是 claude/hermes/all 之一")

    dry_run = arguments.get("dry_run", False)
    if not isinstance(dry_run, bool):
        return _tool_error("参数 dry_run 必须是布尔值 true 或 false")

    confirm_write = arguments.get("confirm_write", False)
    if not isinstance(confirm_write, bool):
        return _tool_error("参数 confirm_write 必须是布尔值 true 或 false")

    return days, source, dry_run, confirm_write


def _tool_error(message: str) -> CallToolResult:
    """Return a standard MCP tool error response."""
    return CallToolResult(
        content=[TextContent(type="text", text=message)],
        isError=True,
    )
