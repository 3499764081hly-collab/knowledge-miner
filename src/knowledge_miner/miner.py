"""Knowledge mining orchestration shared by CLI and MCP."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from knowledge_miner.analyzers.insights import InsightExtractor
from knowledge_miner.config import KnowledgeMinerConfig, get_config
from knowledge_miner.extractors import registry
from knowledge_miner.models import KnowledgeBase, Message
from knowledge_miner.output.ai_knowledge_base import summarize_ai_knowledge_base_update
from knowledge_miner.output.json_writer import JsonWriter


@dataclass
class MiningResult:
    """Result of a knowledge mining pass."""

    knowledge_base: KnowledgeBase | None
    output_path: Path
    sources: list[str]
    days: int
    messages: list[Message]
    date_range: tuple[datetime, datetime]
    skipped_sources: list[str]
    extraction_diagnostics: list[dict[str, Any]]
    preview: dict[str, Any]

    @property
    def session_count(self) -> int:
        return len({message.session_id for message in self.messages})


def mine_knowledge(
    days: int = 7,
    source: str = "all",
    output_path: Path | None = None,
    config: KnowledgeMinerConfig | None = None,
) -> MiningResult:
    """Extract and analyze knowledge without writing it to disk."""
    config = config or get_config()
    target_path = output_path or config.output_path
    sources = [source] if source != "all" else config.data_sources
    since = datetime.now() - timedelta(days=days)

    messages: list[Message] = []
    skipped_sources: list[str] = []
    extraction_diagnostics: list[dict[str, Any]] = []
    date_range_start = datetime.now()
    date_range_end = datetime.now()

    for src in sources:
        extractor = registry.get(src)
        if not extractor or not extractor.validate():
            skipped_sources.append(src)
            continue

        source_messages = extractor.extract_messages(since=since)
        extraction_diagnostics.append(extractor.get_diagnostics())
        messages.extend(source_messages)

        if source_messages:
            timestamps = [message.timestamp for message in source_messages]
            date_range_start = min(date_range_start, min(timestamps))
            date_range_end = max(date_range_end, max(timestamps))

    if not messages:
        return MiningResult(
            knowledge_base=None,
            output_path=target_path,
            sources=sources,
            days=days,
            messages=[],
            date_range=(date_range_start, date_range_end),
            skipped_sources=skipped_sources,
            extraction_diagnostics=extraction_diagnostics,
            preview={
                "will_write": False,
                "reason": "no_messages",
                "output_path": str(target_path),
                "extraction_diagnostics": extraction_diagnostics,
            },
        )

    knowledge_base = InsightExtractor().extract_knowledge(
        messages=messages,
        sources=sources,
        date_range=(date_range_start, date_range_end),
    )
    preview = build_preview(knowledge_base, target_path, extraction_diagnostics)

    return MiningResult(
        knowledge_base=knowledge_base,
        output_path=target_path,
        sources=sources,
        days=days,
        messages=messages,
        date_range=(date_range_start, date_range_end),
        skipped_sources=skipped_sources,
        extraction_diagnostics=extraction_diagnostics,
        preview=preview,
    )


def build_preview(
    knowledge_base: KnowledgeBase,
    output_path: Path,
    extraction_diagnostics: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a dry-run summary for a knowledge base update."""
    writer = JsonWriter(output_path)
    existing_data = writer.read()
    pitfalls = knowledge_base.pitfalls.get("items", [])
    patterns = knowledge_base.thinking_patterns.get("items", [])
    workflows = knowledge_base.workflows.get("items", [])

    return {
        "will_write": True,
        "output_path": str(output_path),
        "knowledge_counts": {
            "pitfalls": len(pitfalls),
            "thinking_patterns": len(patterns),
            "workflows": len(workflows),
        },
        "storage": summarize_ai_knowledge_base_update(
            knowledge_base=knowledge_base,
            output_path=output_path,
            existing_data=existing_data,
        ),
        "extraction_diagnostics": extraction_diagnostics or [],
    }
