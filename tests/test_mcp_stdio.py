import json
import os
import sys
from pathlib import Path

import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


@pytest.mark.asyncio
async def test_mcp_stdio_session_lists_tools_and_respects_confirm_write(
    tmp_path: Path,
) -> None:
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
    output_path = tmp_path / "knowledge-base.json"
    env = os.environ.copy()
    env.update(
        {
            "KM_DATA_SOURCES": "hermes",
            "KM_HERMES_DIR": str(sessions_dir),
            "KM_OUTPUT_PATH": str(output_path),
            "PYTHONPATH": _pythonpath_with_src(env),
        }
    )
    server = StdioServerParameters(
        command=sys.executable,
        args=["-c", "from knowledge_miner.cli import main; main(['mcp-server'])"],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
    )

    async with stdio_client(server) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = await session.list_tools()
            preview = await session.call_tool(
                "mine_knowledge",
                {"source": "hermes", "days": 30},
            )
            assert "未提供 confirm_write=true" in preview.content[0].text
            assert not output_path.exists()

            written = await session.call_tool(
                "mine_knowledge",
                {"source": "hermes", "days": 30, "confirm_write": True},
            )

    assert [tool.name for tool in tools.tools] == [
        "mine_knowledge",
        "get_knowledge",
        "record_knowledge",
        "get_stats",
    ]
    assert "知识沉淀完成" in written.content[0].text
    assert output_path.exists()


def _pythonpath_with_src(env: dict[str, str]) -> str:
    src = str(Path(__file__).resolve().parents[1] / "src")
    existing = env.get("PYTHONPATH")
    if not existing:
        return src
    return f"{src}{os.pathsep}{existing}"
