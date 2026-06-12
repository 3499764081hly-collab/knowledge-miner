import json
from pathlib import Path

import pytest

from knowledge_miner.config import KnowledgeMinerConfig, set_config
from knowledge_miner.mcp_server import call_tool, list_tools


def configure_hermes_source(tmp_path: Path) -> Path:
    sessions_dir = tmp_path / "hermes"
    sessions_dir.mkdir()
    (sessions_dir / "s1.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "role": "user",
                        "timestamp": "2026-06-10T12:00:00",
                        "content": "为什么 pytest 报错？",
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "role": "assistant",
                        "timestamp": "2026-06-10T12:00:01",
                        "content": "失败: pytest 断言失败\n修复: 更新测试期望",
                    },
                    ensure_ascii=False,
                ),
            ]
        ),
        encoding="utf-8",
    )
    output_path = tmp_path / "AI-Knowledge-Base" / "knowledge-base.json"
    set_config(
        KnowledgeMinerConfig(
            data_sources=["hermes"],
            hermes_sessions_dir=sessions_dir,
            output_path=output_path,
        )
    )
    return output_path


@pytest.mark.asyncio
async def test_mcp_lists_expected_tools() -> None:
    result = await list_tools()

    assert [tool.name for tool in result.tools] == [
        "mine_knowledge",
        "get_knowledge",
        "get_stats",
    ]
    mine_tool = result.tools[0]
    assert "dry_run" in mine_tool.inputSchema["properties"]
    assert "confirm_write" in mine_tool.inputSchema["properties"]


@pytest.mark.asyncio
async def test_mcp_unknown_tool_returns_error() -> None:
    result = await call_tool("missing_tool", {})

    assert result.isError is True
    assert "未知工具" in result.content[0].text


@pytest.mark.asyncio
async def test_mcp_get_knowledge_handles_missing_file(tmp_path: Path) -> None:
    set_config(KnowledgeMinerConfig(output_path=tmp_path / "missing.json"))

    result = await call_tool("get_knowledge", {"section": "all"})

    assert result.isError is False
    assert "知识库不存在" in result.content[0].text


@pytest.mark.asyncio
async def test_mcp_get_knowledge_reads_agent_view_from_ai_schema(tmp_path: Path) -> None:
    output_path = tmp_path / "knowledge-base.json"
    output_path.write_text(
        """
{
  "version": "2.0",
  "categories": {
    "bug修复": [],
    "新功能": [],
    "最佳实践": [],
    "行业动态": []
  },
  "agent_knowledge": {
    "metadata": {"sources": ["hermes"], "total_messages": 3},
    "pitfalls": {"priority": "A", "items": [{"id": "pitfall_001"}]},
    "thinking_patterns": {"priority": "B", "items": []},
    "workflows": {"priority": "C", "items": []},
    "communication_style": {"priority": "D", "language": "chinese_preferred"}
  }
}
""".strip(),
        encoding="utf-8",
    )
    set_config(KnowledgeMinerConfig(output_path=output_path))

    result = await call_tool("get_knowledge", {"section": "pitfalls"})

    assert "agent_knowledge" not in result.content[0].text
    assert "pitfall_001" in result.content[0].text


@pytest.mark.asyncio
async def test_mcp_mine_knowledge_dry_run_does_not_write(tmp_path: Path) -> None:
    output_path = configure_hermes_source(tmp_path)

    result = await call_tool("mine_knowledge", {"source": "hermes", "days": 30, "dry_run": True})

    assert "dry-run 预览" in result.content[0].text
    assert "would_add" in result.content[0].text
    assert not output_path.exists()


@pytest.mark.asyncio
async def test_mcp_mine_knowledge_without_confirm_write_does_not_write(
    tmp_path: Path,
) -> None:
    output_path = configure_hermes_source(tmp_path)

    result = await call_tool("mine_knowledge", {"source": "hermes", "days": 30})

    assert "未提供 confirm_write=true" in result.content[0].text
    assert "would_add" in result.content[0].text
    assert not output_path.exists()


@pytest.mark.asyncio
async def test_mcp_mine_knowledge_confirm_write_writes(tmp_path: Path) -> None:
    output_path = configure_hermes_source(tmp_path)

    result = await call_tool(
        "mine_knowledge",
        {"source": "hermes", "days": 30, "confirm_write": True},
    )

    assert "知识沉淀完成" in result.content[0].text
    assert output_path.exists()


@pytest.mark.asyncio
async def test_mcp_mine_knowledge_rejects_string_confirm_write(
    tmp_path: Path,
) -> None:
    output_path = configure_hermes_source(tmp_path)

    result = await call_tool(
        "mine_knowledge",
        {"source": "hermes", "days": 30, "confirm_write": "false"},
    )

    assert result.isError is True
    assert "confirm_write" in result.content[0].text
    assert not output_path.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "arguments, message",
    [
        ({"source": "hermes", "days": 0}, "days"),
        ({"source": "hermes", "days": 366}, "days"),
        ({"source": "missing", "days": 30}, "source"),
        ({"source": "hermes", "days": 30, "dry_run": "true"}, "dry_run"),
        ({"source": "hermes", "days": 30, "extra": True}, "未知参数"),
    ],
)
async def test_mcp_mine_knowledge_rejects_invalid_arguments(
    tmp_path: Path,
    arguments: dict,
    message: str,
) -> None:
    output_path = configure_hermes_source(tmp_path)

    result = await call_tool("mine_knowledge", arguments)

    assert result.isError is True
    assert message in result.content[0].text
    assert not output_path.exists()


@pytest.mark.asyncio
async def test_mcp_get_stats_rejects_unexpected_arguments(tmp_path: Path) -> None:
    set_config(KnowledgeMinerConfig(output_path=tmp_path / "missing.json"))

    result = await call_tool("get_stats", {"unexpected": True})

    assert result.isError is True
    assert "不接受任何参数" in result.content[0].text
