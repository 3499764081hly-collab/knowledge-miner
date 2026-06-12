from datetime import datetime

from knowledge_miner.output.feishu_doc import (
    parse_outline,
    record_to_feishu_xml,
    select_outline_target,
)
from knowledge_miner.record import KnowledgeRecord


def test_parse_outline_extracts_headings() -> None:
    content = (
        '<fragment mode="outline"><outline>'
        '<h2 id="h1">⚠️ 踩过的坑</h2>'
        '<h3 id="h2">配置类</h3>'
        "</outline></fragment>"
    )

    assert parse_outline(content) == [
        {"level": "2", "id": "h1", "text": "⚠️ 踩过的坑"},
        {"level": "3", "id": "h2", "text": "配置类"},
    ]


def test_select_outline_target_prefers_subcategory() -> None:
    outline = [
        {"level": "2", "id": "thinking", "text": "🧠 思维方式"},
        {"level": "2", "id": "pitfall", "text": "⚠️ 踩过的坑"},
        {"level": "3", "id": "config", "text": "配置类"},
    ]
    record = KnowledgeRecord(
        record_type="pitfall",
        title="配置经验",
        summary="配置变更前先 dry-run。",
        subcategory="配置类",
    )

    assert select_outline_target(outline, record)["id"] == "config"


def test_record_to_feishu_xml_escapes_text() -> None:
    record = KnowledgeRecord(
        record_type="pitfall",
        title="A < B",
        summary="先确认 A & B",
        solution="使用 confirm_write=true\n再写入",
        source_agent="pytest",
        tags=["安全", "MCP"],
        created_at=datetime(2026, 6, 12, 10, 30),
    )

    xml = record_to_feishu_xml(record)

    assert "<h3>A &lt; B</h3>" in xml
    assert "先确认 A &amp; B" in xml
    assert "confirm_write=true<br/>再写入" in xml
    assert "安全、MCP" in xml
