"""基础提取器接口"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any

from knowledge_miner.models import Message, Session


class BaseExtractor(ABC):
    """数据源提取器基类"""

    def __init__(self) -> None:
        self.reset_diagnostics()

    @property
    @abstractmethod
    def name(self) -> str:
        """提取器名称（如 'claude', 'hermes'）"""
        ...

    @property
    @abstractmethod
    def display_name(self) -> str:
        """显示名称（如 'Claude Code', 'Hermes'）"""
        ...

    @abstractmethod
    def get_data_path(self) -> Path:
        """获取数据源路径"""
        ...

    @abstractmethod
    def discover_sessions(self, since: datetime | None = None) -> list[Session]:
        """发现所有会话"""
        ...

    @abstractmethod
    def parse_session(self, session_path: Path) -> Session | None:
        """解析单个会话文件"""
        ...

    def extract_messages(
        self,
        since: datetime | None = None,
        limit: int | None = None,
    ) -> list[Message]:
        """提取所有消息"""
        self.reset_diagnostics()
        sessions = self.discover_sessions(since)
        messages: list[Message] = []

        for session in sessions:
            for msg in session.messages:
                messages.append(msg)

        # 按时间排序
        messages.sort(key=lambda m: m.timestamp)

        if limit:
            messages = messages[-limit:]

        return messages

    def validate(self) -> bool:
        """验证数据源是否可用"""
        data_path = self.get_data_path()
        return data_path.exists() and data_path.is_dir()

    def reset_diagnostics(self) -> None:
        """Reset per-run parse diagnostics."""
        self.diagnostics: dict[str, Any] = {
            "files_seen": 0,
            "files_parsed": 0,
            "files_empty": 0,
            "files_skipped_since": 0,
            "bad_lines": 0,
            "bad_messages": 0,
            "file_errors": [],
        }

    def get_diagnostics(self) -> dict[str, Any]:
        """Return a serializable diagnostics snapshot."""
        return {
            "source": self.name,
            "display_name": self.display_name,
            "data_path": str(self.get_data_path()),
            **self.diagnostics,
        }

    def _record_file_error(self, path: Path, error: Exception) -> None:
        errors = self.diagnostics["file_errors"]
        if len(errors) < 10:
            errors.append({"path": str(path), "error": str(error)})

    def _filter_session_since(
        self,
        session: Session,
        since: datetime | None,
    ) -> Session | None:
        """Keep recent messages from a session instead of dropping old sessions."""
        if since is None:
            return session

        messages = [message for message in session.messages if message.timestamp >= since]
        if not messages:
            self.diagnostics["files_skipped_since"] += 1
            return None

        return Session(
            id=session.id,
            source=session.source,
            messages=messages,
            started_at=min(message.timestamp for message in messages),
            project=session.project,
        )
