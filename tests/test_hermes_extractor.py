import json
from datetime import datetime, timedelta
from pathlib import Path

from knowledge_miner.config import KnowledgeMinerConfig, set_config
from knowledge_miner.extractors.hermes import HermesExtractor


def test_hermes_extractor_reports_parse_diagnostics_and_filters_messages(
    tmp_path: Path,
) -> None:
    sessions_dir = tmp_path / "hermes"
    sessions_dir.mkdir()
    session_file = sessions_dir / "session-1.jsonl"
    recent = datetime.now() - timedelta(hours=1)
    old = datetime.now() - timedelta(days=30)
    entries = [
        {
            "role": "user",
            "timestamp": old.isoformat(),
            "content": "旧消息",
        },
        "{not-json",
        {
            "role": "assistant",
            "timestamp": recent.isoformat(),
            "content": "最近的修复经验",
        },
        {
            "role": "assistant",
            "timestamp": recent.isoformat(),
            "content": [],
        },
    ]
    session_file.write_text(
        "\n".join(
            item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)
            for item in entries
        ),
        encoding="utf-8",
    )
    set_config(KnowledgeMinerConfig(data_sources=["hermes"], hermes_sessions_dir=sessions_dir))
    extractor = HermesExtractor()

    messages = extractor.extract_messages(since=datetime.now() - timedelta(days=1))
    diagnostics = extractor.get_diagnostics()

    assert [message.content for message in messages] == ["最近的修复经验"]
    assert diagnostics["files_seen"] == 1
    assert diagnostics["files_parsed"] == 1
    assert diagnostics["bad_lines"] == 1
    assert diagnostics["bad_messages"] == 1
