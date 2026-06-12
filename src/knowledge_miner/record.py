"""Direct agent-submitted knowledge records."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from knowledge_miner.models import KnowledgeBase, create_empty_knowledge_base

RECORD_TYPES = {"pitfall", "thinking_pattern", "workflow"}


@dataclass
class KnowledgeRecord:
    """A single knowledge item submitted directly by an agent."""

    record_type: str
    title: str
    summary: str
    solution: str | None = None
    context: str | None = None
    source_agent: str | None = None
    subcategory: str | None = None
    tags: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)

    def __post_init__(self) -> None:
        if self.record_type not in RECORD_TYPES:
            raise ValueError("record_type 必须是 pitfall/thinking_pattern/workflow 之一")
        self.title = _required_text(self.title, "title")
        self.summary = _required_text(self.summary, "summary")
        self.solution = _optional_text(self.solution)
        self.context = _optional_text(self.context)
        self.source_agent = _optional_text(self.source_agent)
        self.subcategory = _optional_text(self.subcategory)
        self.tags = [tag.strip() for tag in self.tags if isinstance(tag, str) and tag.strip()]

    @property
    def fingerprint(self) -> str:
        raw = "|".join(
            [
                self.record_type,
                self.title,
                self.summary,
                self.solution or "",
                self.subcategory or "",
            ]
        )
        return "fp_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def record_to_knowledge_base(record: KnowledgeRecord) -> KnowledgeBase:
    """Convert one direct record into a small KnowledgeBase update payload."""
    now = record.created_at
    knowledge_base = create_empty_knowledge_base(
        sources=[record.source_agent or "direct_agent"],
        date_range=(now, now),
        total_sessions=1,
    )
    knowledge_base.metadata["total_messages"] = 1
    knowledge_base.metadata["submission_mode"] = "direct_record"

    if record.record_type == "pitfall":
        knowledge_base.pitfalls["items"] = [
            {
                "id": _record_id("pitfall", record),
                "fingerprint": record.fingerprint,
                "category": record.subcategory or "主动沉淀",
                "mistake": record.summary,
                "fix": record.solution or "",
                "frequency": 1,
                "context": record.context or "",
                "examples": _examples(record),
                "last_seen": now.isoformat(),
                "source_agent": record.source_agent,
                "tags": record.tags,
                "title": record.title,
            }
        ]
    elif record.record_type == "thinking_pattern":
        knowledge_base.thinking_patterns["items"] = [
            {
                "id": _record_id("pattern", record),
                "fingerprint": record.fingerprint,
                "name": record.title,
                "description": record.summary,
                "frequency": 1.0,
                "context": record.context or "",
                "examples": _examples(record),
                "last_seen": now.isoformat(),
                "source_agent": record.source_agent,
                "tags": record.tags,
            }
        ]
    else:
        knowledge_base.workflows["items"] = [
            {
                "id": _record_id("workflow", record),
                "fingerprint": record.fingerprint,
                "name": record.title,
                "steps": [record.summary],
                "frequency": 1,
                "context": record.context or "",
                "last_seen": now.isoformat(),
                "source_agent": record.source_agent,
                "tags": record.tags,
            }
        ]

    return knowledge_base


def record_preview(record: KnowledgeRecord, targets: list[str]) -> dict[str, Any]:
    return {
        "will_write": False,
        "record": {
            "type": record.record_type,
            "title": record.title,
            "summary": record.summary,
            "solution": record.solution,
            "subcategory": record.subcategory,
            "source_agent": record.source_agent,
            "tags": record.tags,
            "fingerprint": record.fingerprint,
        },
        "targets": targets,
    }


def _record_id(prefix: str, record: KnowledgeRecord) -> str:
    return f"{prefix}_{record.fingerprint.removeprefix('fp_')}"


def _examples(record: KnowledgeRecord) -> list[str]:
    return [record.context] if record.context else []


def _required_text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} 不能为空")
    return value.strip()


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None
