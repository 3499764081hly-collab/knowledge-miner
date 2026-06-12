import json
from datetime import datetime, timedelta
from pathlib import Path

from knowledge_miner.config import KnowledgeMinerConfig, set_config
from knowledge_miner.extractors.claude import ClaudeExtractor


def test_claude_extractor_preserves_tool_blocks(tmp_path: Path) -> None:
    session_file = tmp_path / "project-a" / "session-1.jsonl"
    session_file.parent.mkdir()
    entries = [
        {
            "type": "assistant",
            "timestamp": "2026-06-10T12:00:00Z",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "我先运行测试。"},
                    {
                        "type": "tool_use",
                        "id": "toolu_1",
                        "name": "Bash",
                        "input": {"command": "pytest -q"},
                    },
                ],
            },
        },
        {
            "type": "user",
            "timestamp": "2026-06-10T12:00:03Z",
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_1",
                        "content": "Exit code: 1\nFAILED tests/test_demo.py",
                    }
                ],
            },
        },
    ]
    session_file.write_text(
        "\n".join(json.dumps(entry, ensure_ascii=False) for entry in entries),
        encoding="utf-8",
    )

    session = ClaudeExtractor().parse_session(session_file)

    assert session is not None
    assert session.project == "project-a"
    assert len(session.messages) == 2
    assert "[tool_use:Bash] command=pytest -q" in session.messages[0].content
    assert session.messages[0].metadata["tool_uses"][0]["name"] == "Bash"
    assert session.messages[0].metadata["tool_uses"][0]["input"]["command"] == "pytest -q"
    assert "Exit code: 1" in session.messages[1].content
    assert session.messages[1].metadata["tool_results"][0]["tool_use_id"] == "toolu_1"


def test_claude_extractor_reports_parse_diagnostics_and_keeps_recent_messages(
    tmp_path: Path,
) -> None:
    projects_dir = tmp_path / "claude"
    session_file = projects_dir / "project-a" / "session-1.jsonl"
    session_file.parent.mkdir(parents=True)
    recent = datetime.now() - timedelta(hours=1)
    old = datetime.now() - timedelta(days=30)
    entries = [
        {
            "type": "user",
            "timestamp": old.isoformat(),
            "message": {"role": "user", "content": "旧消息"},
        },
        "{not-json",
        {
            "type": "assistant",
            "timestamp": recent.isoformat(),
            "message": {"role": "assistant", "content": "最近的修复经验"},
        },
        {
            "type": "assistant",
            "timestamp": recent.isoformat(),
            "message": {"role": "assistant", "content": []},
        },
    ]
    session_file.write_text(
        "\n".join(
            item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)
            for item in entries
        ),
        encoding="utf-8",
    )
    set_config(KnowledgeMinerConfig(data_sources=["claude"], claude_projects_dir=projects_dir))
    extractor = ClaudeExtractor()

    messages = extractor.extract_messages(since=datetime.now() - timedelta(days=1))
    diagnostics = extractor.get_diagnostics()

    assert [message.content for message in messages] == ["最近的修复经验"]
    assert diagnostics["files_seen"] == 1
    assert diagnostics["files_parsed"] == 1
    assert diagnostics["bad_lines"] == 1
    assert diagnostics["bad_messages"] == 1
