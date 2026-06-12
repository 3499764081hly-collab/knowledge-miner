"""JSON 输出模块"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from knowledge_miner.models import KnowledgeBase
from knowledge_miner.output.ai_knowledge_base import (
    should_use_ai_knowledge_base_schema,
    to_ai_knowledge_base_dict,
)


class JsonWriter:
    """JSON 文件写入器"""

    def __init__(self, output_path: str | Path):
        self.output_path = Path(output_path).expanduser()
        self.last_backup_path: Path | None = None
        self.last_corrupt_backup_path: Path | None = None

    def write(self, knowledge_base: KnowledgeBase) -> Path:
        """写入知识库到 JSON 文件"""
        # 确保目录存在
        self.output_path.parent.mkdir(parents=True, exist_ok=True)

        with self._locked():
            existing_data = self.read()
            if should_use_ai_knowledge_base_schema(self.output_path, existing_data):
                payload = to_ai_knowledge_base_dict(knowledge_base, existing_data)
            else:
                payload = knowledge_base.to_dict()

            self.last_backup_path = self.backup_existing()
            temp_path = self._write_temp_payload(payload)
            temp_path.replace(self.output_path)
            self._fsync_parent_dir()
        return self.output_path

    def backup_existing(self) -> Path | None:
        """Create a timestamped backup before overwriting an existing file."""
        if not self.output_path.exists():
            return None

        backup_path = self._unique_backup_path(".bak")
        backup_path.write_bytes(self.output_path.read_bytes())
        return backup_path

    def backup_corrupt(self) -> Path | None:
        """Create a timestamped backup for an unreadable JSON file."""
        if not self.output_path.exists():
            return None

        backup_path = self._unique_backup_path(".corrupt.bak")
        backup_path.write_bytes(self.output_path.read_bytes())
        self.last_corrupt_backup_path = backup_path
        return backup_path

    def _unique_backup_path(self, suffix: str) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = self.output_path.with_name(f"{self.output_path.name}.{timestamp}{suffix}")
        counter = 1
        while backup_path.exists():
            backup_path = self.output_path.with_name(
                f"{self.output_path.name}.{timestamp}.{counter}{suffix}"
            )
            counter += 1
        return backup_path

    def read(self) -> dict[str, Any] | None:
        """读取知识库 JSON 文件"""
        if not self.output_path.exists():
            return None

        try:
            with open(self.output_path, encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError as exc:
            backup_path = self.backup_corrupt()
            raise ValueError(
                f"知识库 JSON 损坏，已备份到 {backup_path}，请修复后再写入"
            ) from exc

    def exists(self) -> bool:
        """检查知识库文件是否存在"""
        return self.output_path.exists()

    def _write_temp_payload(self, payload: dict[str, Any]) -> Path:
        temp_file = tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            delete=False,
            dir=self.output_path.parent,
            prefix=f".{self.output_path.name}.",
            suffix=".tmp",
        )
        temp_path = Path(temp_file.name)
        try:
            with temp_file as f:
                json.dump(
                    payload,
                    f,
                    indent=2,
                    ensure_ascii=False,
                    default=str,
                )
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise
        return temp_path

    @contextlib.contextmanager
    def _locked(self):
        lock_path = self.output_path.with_name(f".{self.output_path.name}.lock")
        with open(lock_path, "w", encoding="utf-8") as lock_file:
            try:
                import fcntl

                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            except ImportError:
                pass
            try:
                yield
            finally:
                try:
                    import fcntl

                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                except ImportError:
                    pass

    def _fsync_parent_dir(self) -> None:
        if not hasattr(os, "O_DIRECTORY"):
            return
        try:
            dir_fd = os.open(self.output_path.parent, os.O_RDONLY | os.O_DIRECTORY)
        except OSError:
            return
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
