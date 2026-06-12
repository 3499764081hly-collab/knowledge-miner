"""Hermes 飞书机器人会话提取器"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from knowledge_miner.config import get_config
from knowledge_miner.extractors import register_extractor
from knowledge_miner.extractors.base import BaseExtractor
from knowledge_miner.models import Message, Session


@register_extractor("hermes")
class HermesExtractor(BaseExtractor):
    """Hermes 飞书机器人会话提取器"""

    @property
    def name(self) -> str:
        return "hermes"

    @property
    def display_name(self) -> str:
        return "Hermes (飞书)"

    def get_data_path(self) -> Path:
        config = get_config()
        return config.hermes_sessions_dir

    def discover_sessions(self, since: datetime | None = None) -> list[Session]:
        """发现所有 Hermes 会话"""
        sessions: list[Session] = []
        data_path = self.get_data_path()

        if not data_path.exists():
            return sessions

        # 查找 JSONL 会话文件
        for session_file in data_path.glob("*.jsonl"):
            self.diagnostics["files_seen"] += 1
            session = self.parse_session(session_file)
            if session:
                filtered = self._filter_session_since(session, since)
                if filtered:
                    sessions.append(filtered)

        return sessions

    def parse_session(self, session_path: Path) -> Session | None:
        """解析 Hermes JSONL 会话文件"""
        try:
            messages: list[Message] = []
            session_id = session_path.stem
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

                    # Hermes 格式：直接在顶层有 role
                    msg_type = data.get("role")
                    if msg_type not in ("user", "assistant"):
                        continue

                    message = self._parse_message(data, session_id)
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
            )
        except Exception as exc:
            self._record_file_error(session_path, exc)
            return None

    def _parse_message(self, data: dict, session_id: str) -> Message | None:
        """解析单条消息"""
        try:
            # Hermes 格式：直接在顶层有 role 和 content
            role = data.get("role")
            if role not in ("user", "assistant"):
                return None

            # 提取时间戳
            timestamp_str = data.get("timestamp")
            if timestamp_str:
                try:
                    timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                except ValueError:
                    timestamp = datetime.now()
            else:
                timestamp = datetime.now()

            # 提取内容（直接在顶层）
            content = data.get("content", "")

            # 处理内容块（如果是列表格式）
            if isinstance(content, list):
                text_parts = []
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "text":
                            text_parts.append(block.get("text", ""))
                content = "\n".join(text_parts)

            if not content or not isinstance(content, str):
                return None

            return Message(
                role=role,
                content=content,
                timestamp=timestamp,
                session_id=session_id,
                source=self.name,
                metadata={
                    "type": role,
                },
            )
        except Exception:
            return None
