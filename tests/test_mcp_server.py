import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from knowledge_miner import mcp_server
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
        "record_knowledge",
        "feishu_auth_status",
        "start_feishu_auth",
        "complete_feishu_auth",
        "set_feishu_doc",
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
async def test_mcp_feishu_auth_status_reports_cli_and_config(monkeypatch) -> None:
    set_config(
        KnowledgeMinerConfig(
            feishu_enabled=True,
            feishu_doc_url="https://example.feishu.cn/wiki/node",
        )
    )

    class FakeFeishuAuthManager:
        def status(self) -> dict[str, object]:
            return {"authenticated": True, "user": "tester"}

    monkeypatch.setattr(mcp_server, "FeishuAuthManager", FakeFeishuAuthManager)

    result = await call_tool("feishu_auth_status", {})

    payload = json.loads(result.content[0].text)
    assert result.isError is False
    assert payload["auth"]["authenticated"] is True
    assert payload["configured"]["feishu_enabled"] is True
    assert payload["configured"]["feishu_doc_url"] == "https://example.feishu.cn/wiki/node"


@pytest.mark.asyncio
async def test_mcp_start_feishu_auth_returns_url_and_qr(monkeypatch, tmp_path: Path) -> None:
    qrcode_path = tmp_path / "feishu-auth-qr.png"

    class FakeFeishuAuthManager:
        def start(self, scopes: str):
            return SimpleNamespace(
                verification_url="https://passport.feishu.cn/device",
                qrcode_path=qrcode_path,
                expires_in=600,
                scopes=scopes,
            )

    monkeypatch.setattr(mcp_server, "FeishuAuthManager", FakeFeishuAuthManager)

    result = await call_tool("start_feishu_auth", {"scopes": "docx:document:write_only"})

    assert result.isError is False
    assert "https://passport.feishu.cn/device" in result.content[0].text
    assert str(qrcode_path) in result.content[0].text
    assert f"![Feishu auth QR]({qrcode_path})" in result.content[0].text
    assert "complete_feishu_auth" in result.content[0].text


@pytest.mark.asyncio
async def test_mcp_start_feishu_auth_returns_setup_url_when_lark_cli_is_unconfigured(
    monkeypatch,
    tmp_path: Path,
) -> None:
    qrcode_path = tmp_path / "feishu-setup-qr.png"
    log_path = tmp_path / "feishu-setup.log"

    class FakeFeishuAuthManager:
        def start(self, scopes: str):
            raise RuntimeError('{"error": {"subtype": "not_configured"}}')

        def start_setup(self):
            return SimpleNamespace(
                setup_url="https://open.feishu.cn/page/cli?user_code=ABCD-EFGH",
                qrcode_path=qrcode_path,
                log_path=log_path,
                pid=12345,
            )

    monkeypatch.setattr(mcp_server, "FeishuAuthManager", FakeFeishuAuthManager)

    result = await call_tool("start_feishu_auth", {})

    assert result.isError is False
    assert "lark-cli 尚未完成首次配置" in result.content[0].text
    assert "https://open.feishu.cn/page/cli?user_code=ABCD-EFGH" in result.content[0].text
    assert str(qrcode_path) in result.content[0].text
    assert f"![Feishu CLI setup QR]({qrcode_path})" in result.content[0].text
    assert "再次调用 start_feishu_auth" in result.content[0].text


@pytest.mark.asyncio
async def test_mcp_complete_feishu_auth_finishes_pending_flow(monkeypatch) -> None:
    calls: list[str | None] = []

    class FakeFeishuAuthManager:
        def complete(self, device_code: str | None = None) -> dict[str, object]:
            calls.append(device_code)
            return {"ok": True}

    monkeypatch.setattr(mcp_server, "FeishuAuthManager", FakeFeishuAuthManager)

    result = await call_tool("complete_feishu_auth", {"device_code": "device-123"})

    assert result.isError is False
    assert calls == ["device-123"]
    assert '"ok": true' in result.content[0].text


@pytest.mark.asyncio
async def test_mcp_set_feishu_doc_defaults_to_preview(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / ".knowledge-miner" / "config.json"
    set_config(KnowledgeMinerConfig(output_path=tmp_path / "knowledge-base.json"))
    monkeypatch.setattr(mcp_server, "_config_file_path", lambda: config_path)

    result = await call_tool(
        "set_feishu_doc",
        {"doc_url": "https://example.feishu.cn/wiki/node"},
    )

    assert result.isError is False
    assert "未提供 confirm_write=true" in result.content[0].text
    assert not config_path.exists()


@pytest.mark.asyncio
async def test_mcp_set_feishu_doc_confirm_write_saves_config(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / ".knowledge-miner" / "config.json"
    set_config(KnowledgeMinerConfig(output_path=tmp_path / "knowledge-base.json"))
    monkeypatch.setattr(mcp_server, "_config_file_path", lambda: config_path)

    result = await call_tool(
        "set_feishu_doc",
        {
            "doc_url": "https://example.feishu.cn/wiki/node",
            "confirm_write": True,
        },
    )

    payload = json.loads(config_path.read_text(encoding="utf-8"))
    assert result.isError is False
    assert "飞书文档已配置" in result.content[0].text
    assert payload["feishu-enabled"] is True
    assert payload["feishu-doc-url"] == "https://example.feishu.cn/wiki/node"


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


@pytest.mark.asyncio
async def test_mcp_record_knowledge_without_confirm_write_does_not_write(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "AI-Knowledge-Base" / "knowledge-base.json"
    set_config(KnowledgeMinerConfig(output_path=output_path))

    result = await call_tool(
        "record_knowledge",
        {
            "record_type": "pitfall",
            "title": "飞书写入先 dry-run",
            "summary": "涉及外部文档写入时，默认必须只预览。",
            "solution": "传 confirm_write=true 才允许写入。",
            "source_agent": "pytest",
        },
    )

    assert result.isError is False
    assert "未提供 confirm_write=true" in result.content[0].text
    assert "飞书写入先 dry-run" in result.content[0].text
    assert not output_path.exists()


@pytest.mark.asyncio
async def test_mcp_record_knowledge_confirm_write_writes_local_ai_schema(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "AI-Knowledge-Base" / "knowledge-base.json"
    set_config(KnowledgeMinerConfig(output_path=output_path))

    result = await call_tool(
        "record_knowledge",
        {
            "record_type": "pitfall",
            "title": "飞书写入先 dry-run",
            "summary": "涉及外部文档写入时，默认必须只预览。",
            "solution": "传 confirm_write=true 才允许写入。",
            "source_agent": "pytest",
            "confirm_write": True,
        },
    )

    data = json.loads(output_path.read_text(encoding="utf-8"))
    assert result.isError is False
    assert "知识记录已沉淀" in result.content[0].text
    assert data["agent_knowledge"]["metadata"]["submission_mode"] == "direct_record"
    assert data["categories"]["bug修复"][0]["summary"] == "涉及外部文档写入时，默认必须只预览。"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "arguments, message",
    [
        ({"record_type": "note", "title": "t", "summary": "s"}, "record_type"),
        ({"record_type": "pitfall", "title": "", "summary": "s"}, "title"),
        ({"record_type": "pitfall", "title": "t", "summary": ""}, "summary"),
        ({"record_type": "pitfall", "title": "t", "summary": "s", "tags": [1]}, "tags"),
        ({"record_type": "pitfall", "title": "t", "summary": "s", "target": "remote"}, "target"),
        ({"record_type": "pitfall", "title": "t", "summary": "s", "dry_run": "true"}, "dry_run"),
        (
            {"record_type": "pitfall", "title": "t", "summary": "s", "confirm_write": "false"},
            "confirm_write",
        ),
        ({"record_type": "pitfall", "title": "t", "summary": "s", "extra": True}, "未知参数"),
    ],
)
async def test_mcp_record_knowledge_rejects_invalid_arguments(
    tmp_path: Path,
    arguments: dict,
    message: str,
) -> None:
    output_path = tmp_path / "knowledge-base.json"
    set_config(KnowledgeMinerConfig(output_path=output_path))

    result = await call_tool("record_knowledge", arguments)

    assert result.isError is True
    assert message in result.content[0].text
    assert not output_path.exists()
