import json
from datetime import datetime
from pathlib import Path

from knowledge_miner.config import KnowledgeMinerConfig, set_config
from knowledge_miner.miner import mine_knowledge


def test_mine_knowledge_preview_includes_extraction_diagnostics(tmp_path: Path) -> None:
    sessions_dir = tmp_path / "hermes"
    sessions_dir.mkdir()
    (sessions_dir / "s1.jsonl").write_text(
        "\n".join(
            [
                "{not-json",
                json.dumps(
                    {
                        "role": "assistant",
                        "timestamp": datetime.now().isoformat(),
                        "content": "失败: pytest 断言失败\n修复: 更新测试期望",
                    },
                    ensure_ascii=False,
                ),
            ]
        ),
        encoding="utf-8",
    )
    set_config(
        KnowledgeMinerConfig(
            data_sources=["hermes"],
            hermes_sessions_dir=sessions_dir,
            output_path=tmp_path / "knowledge-base.json",
        )
    )

    result = mine_knowledge(source="hermes", days=7)

    diagnostics = result.preview["extraction_diagnostics"]
    assert diagnostics[0]["source"] == "hermes"
    assert diagnostics[0]["files_seen"] == 1
    assert diagnostics[0]["files_parsed"] == 1
    assert diagnostics[0]["bad_lines"] == 1
