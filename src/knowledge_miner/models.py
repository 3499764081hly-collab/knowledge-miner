"""数据模型定义"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Message:
    """单条聊天消息"""
    role: str  # user, assistant
    content: str
    timestamp: datetime
    session_id: str
    source: str  # claude, hermes, cursor, etc.
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Session:
    """一个会话（一次对话）"""
    id: str
    source: str
    messages: list[Message]
    started_at: datetime
    project: str | None = None


@dataclass
class Pitfall:
    """踩过的坑"""
    id: str
    category: str
    mistake: str
    fix: str
    frequency: int
    context: str
    examples: list[str] = field(default_factory=list)
    last_seen: datetime | None = None


@dataclass
class ThinkingPattern:
    """思维方式"""
    id: str
    name: str
    description: str
    frequency: float  # 0-1
    context: str
    examples: list[str] = field(default_factory=list)
    last_seen: datetime | None = None


@dataclass
class Workflow:
    """工作流"""
    id: str
    name: str
    steps: list[str]
    frequency: int
    context: str
    last_seen: datetime | None = None


@dataclass
class CommunicationStyle:
    """沟通风格"""
    formality: str  # casual, formal, casual_technical
    detail_level: str  # concise, moderate, detailed
    prefers_examples: bool
    language: str  # chinese_preferred, english_preferred, mixed
    response_preferences: dict[str, Any] = field(default_factory=dict)


@dataclass
class KnowledgeBase:
    """知识库"""
    metadata: dict[str, Any]
    pitfalls: dict[str, Any]
    thinking_patterns: dict[str, Any]
    workflows: dict[str, Any]
    communication_style: dict[str, Any]
    feishu_wiki: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        result = {
            "metadata": self.metadata,
            "pitfalls": self.pitfalls,
            "thinking_patterns": self.thinking_patterns,
            "workflows": self.workflows,
            "communication_style": self.communication_style,
        }
        if self.feishu_wiki:
            result["feishu_wiki"] = self.feishu_wiki
        return result


def create_empty_knowledge_base(
    sources: list[str],
    date_range: tuple[datetime, datetime],
    total_sessions: int = 0,
) -> KnowledgeBase:
    """创建空知识库"""
    return KnowledgeBase(
        metadata={
            "generated_at": datetime.now().isoformat(),
            "version": "1.0.0",
            "sources": sources,
            "total_sessions": total_sessions,
            "date_range": {
                "start": date_range[0].isoformat(),
                "end": date_range[1].isoformat(),
            },
        },
        pitfalls={"priority": "A", "items": []},
        thinking_patterns={"priority": "B", "items": []},
        workflows={"priority": "C", "items": []},
        communication_style={
            "priority": "D",
            "formality": "unknown",
            "detail_level": "unknown",
            "prefers_examples": False,
            "language": "unknown",
            "response_preferences": {},
        },
    )
