from datetime import datetime
from pathlib import Path

import pytest

from knowledge_miner.models import create_empty_knowledge_base
from knowledge_miner.output.ai_knowledge_base import summarize_ai_knowledge_base_update
from knowledge_miner.output.json_writer import JsonWriter


def test_json_writer_accepts_string_paths(tmp_path: Path) -> None:
    output_path = tmp_path / "nested" / "knowledge.json"
    writer = JsonWriter(str(output_path))
    knowledge_base = create_empty_knowledge_base(
        sources=["hermes"],
        date_range=(datetime(2026, 1, 1), datetime(2026, 1, 2)),
        total_sessions=1,
    )

    written_path = writer.write(knowledge_base)
    data = writer.read()

    assert written_path == output_path
    assert data is not None
    assert data["metadata"]["sources"] == ["hermes"]
    assert not output_path.with_suffix(".json.tmp").exists()
    assert writer.last_backup_path is None


def test_json_writer_backs_up_existing_file_before_write(tmp_path: Path) -> None:
    output_path = tmp_path / "knowledge.json"
    output_path.write_text('{"old": true}\n', encoding="utf-8")
    writer = JsonWriter(output_path)
    knowledge_base = create_empty_knowledge_base(
        sources=["hermes"],
        date_range=(datetime(2026, 1, 1), datetime(2026, 1, 2)),
        total_sessions=1,
    )

    writer.write(knowledge_base)

    assert writer.last_backup_path is not None
    assert writer.last_backup_path.exists()
    assert writer.last_backup_path.name.startswith("knowledge.json.")
    assert writer.last_backup_path.name.endswith(".bak")
    assert writer.last_backup_path.read_text(encoding="utf-8") == '{"old": true}\n'
    assert JsonWriter(output_path).read()["metadata"]["sources"] == ["hermes"]


def test_json_writer_refuses_to_overwrite_corrupt_json(tmp_path: Path) -> None:
    output_path = tmp_path / "knowledge.json"
    output_path.write_text('{"broken": ', encoding="utf-8")
    writer = JsonWriter(output_path)
    knowledge_base = create_empty_knowledge_base(
        sources=["hermes"],
        date_range=(datetime(2026, 1, 1), datetime(2026, 1, 2)),
        total_sessions=1,
    )

    with pytest.raises(ValueError, match="JSON 损坏"):
        writer.write(knowledge_base)

    assert output_path.read_text(encoding="utf-8") == '{"broken": '
    assert writer.last_corrupt_backup_path is not None
    assert writer.last_corrupt_backup_path.exists()
    assert writer.last_corrupt_backup_path.name.endswith(".corrupt.bak")
    assert writer.last_corrupt_backup_path.read_text(encoding="utf-8") == '{"broken": '
    assert writer.last_backup_path is None


def test_json_writer_uses_unique_temp_file_without_clobbering_existing_tmp(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "knowledge.json"
    stale_tmp = output_path.with_suffix(".json.tmp")
    stale_tmp.write_text("keep me", encoding="utf-8")
    writer = JsonWriter(output_path)
    knowledge_base = create_empty_knowledge_base(
        sources=["hermes"],
        date_range=(datetime(2026, 1, 1), datetime(2026, 1, 2)),
        total_sessions=1,
    )

    writer.write(knowledge_base)

    assert stale_tmp.read_text(encoding="utf-8") == "keep me"
    assert not list(tmp_path.glob(".knowledge.json.*.tmp"))
    assert JsonWriter(output_path).read()["metadata"]["sources"] == ["hermes"]


def test_json_writer_preserves_ai_knowledge_base_schema(tmp_path: Path) -> None:
    output_path = tmp_path / "AI-Knowledge-Base" / "knowledge-base.json"
    output_path.parent.mkdir()
    output_path.write_text(
        """
{
  "version": "1.0",
  "created": "2026-06-10",
  "qa_count": 1,
  "categories": {
    "bug修复": [{"id": "old", "title": "旧问题"}],
    "新功能": [],
    "最佳实践": [],
    "行业动态": []
  },
  "monthly_stats": {"2026-06": 1}
}
""".strip(),
        encoding="utf-8",
    )
    knowledge_base = create_empty_knowledge_base(
        sources=["hermes"],
        date_range=(datetime(2026, 1, 1), datetime(2026, 1, 2)),
        total_sessions=1,
    )
    knowledge_base.pitfalls["items"] = [
        {
            "id": "pitfall_001",
            "category": "API 错误",
            "mistake": "API 456 Forbidden",
            "fix": "检查账号权限",
            "frequency": 2,
            "examples": ["Claude Code 报错 API 456 Forbidden"],
            "last_seen": "2026-06-10T12:00:00",
        }
    ]

    JsonWriter(output_path).write(knowledge_base)
    data = JsonWriter(output_path).read()

    assert data is not None
    assert data["version"] == "2.0"
    assert data["created"] == "2026-06-10"
    assert data["qa_count"] == 1
    assert data["monthly_stats"] == {"2026-06": 1}
    assert data["agent_knowledge"]["metadata"]["sources"] == ["hermes"]
    assert any(item["id"] == "old" for item in data["categories"]["bug修复"])
    assert any(item["id"] == "pitfall_001" for item in data["categories"]["bug修复"])


def test_ai_knowledge_base_schema_merges_items_by_fingerprint(tmp_path: Path) -> None:
    output_path = tmp_path / "AI-Knowledge-Base" / "knowledge-base.json"
    output_path.parent.mkdir()
    output_path.write_text(
        """
{
  "version": "2.0",
  "created": "2026-06-10",
  "qa_count": 0,
  "categories": {
    "bug修复": [
      {
        "id": "old",
        "fingerprint": "fp_same",
        "title": "tool_failure:Bash",
        "summary": "old summary",
        "solution": "old solution",
        "frequency": 2,
        "examples": ["old example"],
        "last_seen": "2026-06-10T12:00:00"
      }
    ],
    "新功能": [],
    "最佳实践": [],
    "行业动态": []
  },
  "agent_knowledge": {},
  "monthly_stats": {}
}
""".strip(),
        encoding="utf-8",
    )
    knowledge_base = create_empty_knowledge_base(
        sources=["claude"],
        date_range=(datetime(2026, 1, 1), datetime(2026, 1, 2)),
        total_sessions=1,
    )
    knowledge_base.pitfalls["items"] = [
        {
            "id": "new",
            "fingerprint": "fp_same",
            "category": "tool_failure:Bash",
            "mistake": "new summary",
            "fix": "new solution",
            "frequency": 1,
            "examples": ["new example"],
            "last_seen": "2026-06-11T12:00:00",
        }
    ]

    JsonWriter(output_path).write(knowledge_base)
    data = JsonWriter(output_path).read()

    items = data["categories"]["bug修复"]
    assert len(items) == 1
    assert items[0]["id"] == "old"
    assert items[0]["summary"] == "new summary"
    assert items[0]["solution"] == "new solution"
    assert items[0]["frequency"] == 3
    assert items[0]["last_seen"] == "2026-06-11T12:00:00"
    assert items[0]["examples"] == ["old example", "new example"]


def test_ai_knowledge_base_schema_preserves_unknown_fields_and_categories(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "AI-Knowledge-Base" / "knowledge-base.json"
    output_path.parent.mkdir()
    output_path.write_text(
        """
{
  "version": "2.0",
  "created": "2026-06-10",
  "qa_count": 0,
  "custom_top_level": {"owner": "user", "keep": true},
  "categories": {
    "bug修复": [
      {
        "id": "old",
        "fingerprint": "fp_same",
        "title": "旧标题",
        "summary": "old summary",
        "frequency": 2,
        "custom_item_field": {"keep": true}
      },
      "legacy-freeform-item"
    ],
    "新功能": [],
    "最佳实践": [],
    "行业动态": [],
    "自定义分类": [
      {
        "id": "custom",
        "title": "用户自己维护的分类"
      }
    ]
  },
  "monthly_stats": {"2026-06": 1}
}
""".strip(),
        encoding="utf-8",
    )
    knowledge_base = create_empty_knowledge_base(
        sources=["claude"],
        date_range=(datetime(2026, 1, 1), datetime(2026, 1, 2)),
        total_sessions=1,
    )
    knowledge_base.pitfalls["items"] = [
        {
            "id": "new",
            "fingerprint": "fp_same",
            "category": "tool_failure:Bash",
            "mistake": "new summary",
            "fix": "new solution",
            "frequency": 1,
        }
    ]

    JsonWriter(output_path).write(knowledge_base)
    data = JsonWriter(output_path).read()

    assert data["custom_top_level"] == {"owner": "user", "keep": True}
    assert data["categories"]["自定义分类"] == [
        {"id": "custom", "title": "用户自己维护的分类"}
    ]
    assert "legacy-freeform-item" in data["categories"]["bug修复"]
    merged_item = next(
        item
        for item in data["categories"]["bug修复"]
        if isinstance(item, dict) and item.get("fingerprint") == "fp_same"
    )
    assert merged_item["custom_item_field"] == {"keep": True}
    assert merged_item["summary"] == "new summary"
    assert merged_item["frequency"] == 3


def test_ai_knowledge_base_preview_includes_samples_and_operations(tmp_path: Path) -> None:
    output_path = tmp_path / "AI-Knowledge-Base" / "knowledge-base.json"
    output_path.parent.mkdir()
    existing_data = {
        "version": "2.0",
        "categories": {
            "bug修复": [{"fingerprint": "fp_existing", "title": "旧问题"}],
            "新功能": [],
            "最佳实践": [],
            "行业动态": [],
        },
    }
    knowledge_base = create_empty_knowledge_base(
        sources=["claude"],
        date_range=(datetime(2026, 1, 1), datetime(2026, 1, 2)),
        total_sessions=1,
    )
    knowledge_base.pitfalls["items"] = [
        {
            "id": "p1",
            "fingerprint": "fp_existing",
            "category": "tool_failure:Bash",
            "mistake": "pytest -q\nFAILED tests/test_demo.py",
            "fix": "后续尝试：Bash: pytest -q",
            "frequency": 1,
        },
        {
            "id": "p2",
            "fingerprint": "fp_new",
            "category": "API 错误",
            "mistake": "API 456 Forbidden",
            "fix": "检查权限",
            "frequency": 1,
        },
    ]

    preview = summarize_ai_knowledge_base_update(
        knowledge_base=knowledge_base,
        output_path=output_path,
        existing_data=existing_data,
    )

    assert preview["would_add"] == 1
    assert preview["would_merge"] == 1
    assert preview["samples"][0]["operation"] == "merge"
    assert preview["samples"][1]["operation"] == "add"
    assert preview["samples"][0]["summary"].startswith("pytest -q")


def test_ai_knowledge_base_preview_lists_preserved_custom_structure(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "AI-Knowledge-Base" / "knowledge-base.json"
    output_path.parent.mkdir()
    existing_data = {
        "version": "2.0",
        "custom_top_level": {"keep": True},
        "categories": {
            "bug修复": [],
            "新功能": [],
            "最佳实践": [],
            "行业动态": [],
            "自定义分类": [{"id": "custom"}],
        },
    }
    knowledge_base = create_empty_knowledge_base(
        sources=["claude"],
        date_range=(datetime(2026, 1, 1), datetime(2026, 1, 2)),
        total_sessions=1,
    )

    preview = summarize_ai_knowledge_base_update(
        knowledge_base=knowledge_base,
        output_path=output_path,
        existing_data=existing_data,
    )

    assert preview["preserved"] == {
        "unknown_top_level_fields": ["custom_top_level"],
        "unknown_categories": ["自定义分类"],
    }


def test_ai_knowledge_base_humanizes_tool_failure_titles(tmp_path: Path) -> None:
    output_path = tmp_path / "AI-Knowledge-Base" / "knowledge-base.json"
    output_path.parent.mkdir()
    knowledge_base = create_empty_knowledge_base(
        sources=["claude"],
        date_range=(datetime(2026, 1, 1), datetime(2026, 1, 2)),
        total_sessions=1,
    )
    knowledge_base.pitfalls["items"] = [
        {
            "id": "p1",
            "fingerprint": "fp_typecheck",
            "category": "tool_failure:Bash",
            "mistake": "npm run typecheck\nsrc/App.tsx(316,38): error TS2322",
            "fix": "后续尝试：Edit: src/App.tsx",
            "frequency": 1,
            "source": "tool_failure_chain",
            "command": "npm run typecheck",
        },
        {
            "id": "p2",
            "fingerprint": "fp_pytest",
            "category": "tool_failure:Bash",
            "mistake": "pytest -q\nFAILED tests/test_demo.py",
            "fix": "后续尝试：Bash: pytest -q",
            "frequency": 1,
            "source": "tool_failure_chain",
            "command": "pytest -q",
        },
    ]

    preview = summarize_ai_knowledge_base_update(
        knowledge_base=knowledge_base,
        output_path=output_path,
        existing_data={"categories": {"bug修复": [], "新功能": [], "最佳实践": [], "行业动态": []}},
    )

    assert preview["samples"][0]["title"] == "TypeScript 类型检查失败：App.tsx"
    assert preview["samples"][0]["summary"].startswith("触发动作：npm run typecheck")
    assert preview["samples"][1]["title"] == "pytest 测试失败：test_demo.py"
