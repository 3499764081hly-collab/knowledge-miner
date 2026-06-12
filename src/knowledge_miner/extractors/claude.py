"""Claude Code 会话提取器"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from knowledge_miner.config import get_config
from knowledge_miner.extractors import register_extractor
from knowledge_miner.extractors.base import BaseExtractor
from knowledge_miner.models import Message, Session

MAX_BLOCK_CHARS = 2000
MAX_METADATA_CHARS = 1000


@register_extractor("claude")
class ClaudeExtractor(BaseExtractor):
    """Claude Code 会话提取器"""

    @property
    def name(self) -> str:
        return "claude"

    @property
    def display_name(self) -> str:
        return "Claude Code"

    def get_data_path(self) -> Path:
        config = get_config()
        return config.claude_projects_dir

    def discover_sessions(self, since: datetime | None = None) -> list[Session]:
        """发现所有 Claude Code 会话"""
        sessions: list[Session] = []
        data_path = self.get_data_path()

        if not data_path.exists():
            return sessions

        # 遍历所有项目目录
        for project_dir in data_path.iterdir():
            if not project_dir.is_dir():
                continue

            # 查找 JSONL 会话文件
            for session_file in project_dir.glob("*.jsonl"):
                self.diagnostics["files_seen"] += 1
                session = self.parse_session(session_file)
                if session:
                    filtered = self._filter_session_since(session, since)
                    if filtered:
                        sessions.append(filtered)

        return sessions

    def parse_session(self, session_path: Path) -> Session | None:
        """解析 Claude Code JSONL 会话文件"""
        try:
            messages: list[Message] = []
            session_id = session_path.stem
            project = session_path.parent.name
            started_at = datetime.fromtimestamp(session_path.stat().st_mtime)

            with open(session_path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        self.diagnostics["bad_lines"] += 1
                        continue

                    # 只提取用户和助手消息
                    msg_type = data.get("type")
                    if msg_type not in ("user", "assistant"):
                        continue

                    message = self._parse_message(data, session_id, project)
                    if message:
                        messages.append(message)
                        # 更新会话开始时间
                        if message.timestamp < started_at:
                            started_at = message.timestamp
                    else:
                        self.diagnostics["bad_messages"] += 1

            if not messages:
                self.diagnostics["files_empty"] += 1
                return None

            self.diagnostics["files_parsed"] += 1
            return Session(
                id=session_id,
                source=self.name,
                messages=messages,
                started_at=started_at,
                project=project,
            )
        except Exception as exc:
            self._record_file_error(session_path, exc)
            return None

    def _parse_message(
        self, data: dict, session_id: str, project: str
    ) -> Message | None:
        """解析单条消息"""
        try:
            msg_type = data.get("type")
            if msg_type not in ("user", "assistant"):
                return None

            timestamp = _parse_timestamp(data.get("timestamp"))

            # 提取内容
            message_data = data.get("message", {})
            content = message_data.get("content", "")

            content, block_metadata = self._parse_content(content)

            if not content or not isinstance(content, str):
                return None

            # 提取角色
            role = message_data.get("role", msg_type)

            return Message(
                role=role,
                content=content,
                timestamp=timestamp,
                session_id=session_id,
                source=self.name,
                metadata={
                    "project": project,
                    "type": msg_type,
                    **block_metadata,
                },
            )
        except Exception:
            return None

    def _parse_content(self, content: Any) -> tuple[str, dict[str, Any]]:
        """Convert Claude content blocks into searchable text and metadata."""
        if isinstance(content, str):
            return content, {"tool_uses": [], "tool_results": []}

        if not isinstance(content, list):
            return "", {"tool_uses": [], "tool_results": []}

        text_parts: list[str] = []
        tool_uses: list[dict[str, Any]] = []
        tool_results: list[dict[str, Any]] = []

        for block in content:
            if not isinstance(block, dict):
                continue

            block_type = block.get("type")
            if block_type == "text":
                text_parts.append(str(block.get("text", "")))
            elif block_type == "thinking":
                text_parts.append(f"[thinking] {_truncate(block.get('thinking', ''))}")
            elif block_type == "tool_use":
                tool_use = _tool_use_metadata(block)
                tool_uses.append(tool_use)
                text_parts.append(
                    f"[tool_use:{tool_use['name']}] {tool_use.get('summary', '')}"
                )
            elif block_type == "tool_result":
                tool_result = _tool_result_metadata(block)
                tool_results.append(tool_result)
                text_parts.append(
                    f"[tool_result:{tool_result.get('tool_use_id', '')}] "
                    f"{tool_result.get('content', '')}"
                )
            elif block_type == "image":
                text_parts.append("[image]")

        return "\n".join(part for part in text_parts if part).strip(), {
            "tool_uses": tool_uses,
            "tool_results": tool_results,
        }


def _parse_timestamp(timestamp_str: str | None) -> datetime:
    if not timestamp_str:
        return datetime.now()
    try:
        timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now()
    if timestamp.tzinfo is not None:
        timestamp = timestamp.astimezone().replace(tzinfo=None)
    return timestamp


def _tool_use_metadata(block: dict[str, Any]) -> dict[str, Any]:
    tool_input = block.get("input", {})
    return {
        "id": block.get("id", ""),
        "name": block.get("name", "unknown"),
        "input": _truncate_nested(tool_input),
        "summary": _summarize_tool_input(tool_input),
    }


def _tool_result_metadata(block: dict[str, Any]) -> dict[str, Any]:
    return {
        "tool_use_id": block.get("tool_use_id", ""),
        "is_error": block.get("is_error", False),
        "content": _truncate(block.get("content", "")),
    }


def _summarize_tool_input(tool_input: Any) -> str:
    if not isinstance(tool_input, dict):
        return _truncate(tool_input)

    priority_keys = ("command", "file_path", "path", "url", "pattern", "query")
    for key in priority_keys:
        if key in tool_input and tool_input[key]:
            return f"{key}={_truncate(tool_input[key])}"
    return _truncate(json.dumps(tool_input, ensure_ascii=False, sort_keys=True))


def _truncate_nested(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _truncate_nested(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_truncate_nested(v) for v in value[:20]]
    return _truncate(value, MAX_METADATA_CHARS)


def _truncate(value: Any, max_chars: int = MAX_BLOCK_CHARS) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."
