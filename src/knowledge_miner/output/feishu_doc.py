"""Feishu/Lark Docx writer for direct knowledge records."""

from __future__ import annotations

import html
import json
import re
import subprocess
from dataclasses import dataclass
from typing import Any

from knowledge_miner.record import KnowledgeRecord


@dataclass
class FeishuWriteResult:
    """Result from writing one record into a Feishu document."""

    doc: str
    block_id: str
    heading: str
    revision_id: int | None


class FeishuDocWriter:
    """Write direct knowledge records into an existing Feishu Docx/Wiki document."""

    def __init__(self, doc: str, cli: str = "lark-cli") -> None:
        self.doc = doc
        self.cli = cli

    def preview(self, record: KnowledgeRecord) -> dict[str, Any]:
        outline = self.fetch_outline()
        target = select_outline_target(outline, record)
        return {
            "doc": self.doc,
            "target_heading": target["text"],
            "target_block_id": target["id"],
            "content": record_to_feishu_xml(record),
        }

    def write(self, record: KnowledgeRecord) -> FeishuWriteResult:
        outline = self.fetch_outline()
        target = select_outline_target(outline, record)
        payload = self._run(
            [
                self.cli,
                "docs",
                "+update",
                "--api-version",
                "v2",
                "--as",
                "user",
                "--doc",
                self.doc,
                "--command",
                "block_insert_after",
                "--block-id",
                target["id"],
                "--content",
                record_to_feishu_xml(record),
                "--format",
                "json",
            ]
        )
        document = payload.get("data", {}).get("document", {})
        return FeishuWriteResult(
            doc=self.doc,
            block_id=target["id"],
            heading=target["text"],
            revision_id=document.get("revision_id"),
        )

    def fetch_outline(self) -> list[dict[str, str]]:
        payload = self._run(
            [
                self.cli,
                "docs",
                "+fetch",
                "--api-version",
                "v2",
                "--as",
                "user",
                "--doc",
                self.doc,
                "--scope",
                "outline",
                "--max-depth",
                "4",
                "--detail",
                "with-ids",
                "--format",
                "json",
            ]
        )
        content = payload.get("data", {}).get("document", {}).get("content", "")
        return parse_outline(content)

    def _run(self, argv: list[str]) -> dict[str, Any]:
        completed = subprocess.run(
            argv,
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or completed.stdout.strip())
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"lark-cli 返回非 JSON 输出: {completed.stdout[:200]}") from exc
        if not payload.get("ok", False):
            raise RuntimeError(json.dumps(payload.get("error", payload), ensure_ascii=False))
        return payload


def parse_outline(content: str) -> list[dict[str, str]]:
    """Extract heading ids and text from a Feishu XML outline fragment."""
    headings: list[dict[str, str]] = []
    pattern = r"<h(?P<level>[1-6])\s+id=\"(?P<id>[^\"]+)\">(?P<text>.*?)</h\1>"
    for match in re.finditer(pattern, content):
        headings.append(
            {
                "level": match.group("level"),
                "id": match.group("id"),
                "text": html.unescape(re.sub(r"<[^>]+>", "", match.group("text"))),
            }
        )
    return headings


def select_outline_target(
    outline: list[dict[str, str]],
    record: KnowledgeRecord,
) -> dict[str, str]:
    """Pick the best heading to insert after."""
    if record.subcategory:
        normalized_subcategory = _normalize(record.subcategory)
        for heading in outline:
            if normalized_subcategory and normalized_subcategory in _normalize(heading["text"]):
                return heading

    desired = {
        "pitfall": "踩过的坑",
        "thinking_pattern": "思维方式",
        "workflow": "常用工作流",
    }[record.record_type]
    for heading in outline:
        if _normalize(desired) in _normalize(heading["text"]):
            return heading

    if outline:
        return outline[-1]
    raise RuntimeError("飞书文档没有可插入的标题，请先创建知识库大纲")


def record_to_feishu_xml(record: KnowledgeRecord) -> str:
    title = _escape(record.title)
    summary = _escape(record.summary)
    source_agent = _escape(record.source_agent or "agent")
    created = _escape(record.created_at.isoformat(timespec="seconds"))
    subcategory = _escape(record.subcategory or _type_label(record.record_type))
    tags = "、".join(_escape(tag) for tag in record.tags) if record.tags else "-"

    parts = [
        '<callout emoji="📝" background-color="light-yellow" border-color="yellow">',
        f"<h3>{title}</h3>",
        f"<p><b>类型：</b>{_type_label(record.record_type)} / {subcategory}</p>",
        f"<p><b>摘要：</b>{summary}</p>",
    ]
    if record.solution:
        parts.append(f"<p><b>处理方式：</b>{_escape(record.solution)}</p>")
    if record.context:
        parts.append(f"<p><b>上下文：</b>{_escape(record.context)}</p>")
    parts.extend(
        [
            f"<p><b>标签：</b>{tags}</p>",
            f"<p><b>来源：</b>{source_agent} · {created}</p>",
            "</callout>",
        ]
    )
    return "".join(parts)


def _type_label(record_type: str) -> str:
    return {
        "pitfall": "踩坑",
        "thinking_pattern": "思维方式",
        "workflow": "工作流",
    }[record_type]


def _escape(value: str) -> str:
    return html.escape(value, quote=False).replace("\n", "<br/>")


def _normalize(value: str) -> str:
    return re.sub(r"\s+", "", value).lower()
