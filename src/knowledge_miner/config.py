"""配置管理模块"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

VALID_DATA_SOURCES = {"claude", "hermes"}
VALID_GRANULARITIES = {"global", "project", "time"}
VALID_CONTENT_PRIORITIES = {
    "pitfalls",
    "thinking_patterns",
    "workflows",
    "communication_style",
}
CONFIG_FILE_KEYS = {
    "data-sources",
    "claude-projects-dir",
    "hermes-sessions-dir",
    "output-path",
    "feishu-enabled",
    "feishu-space-id",
    "feishu-node-token",
    "analysis-granularity",
    "content-priority",
    "cron-enabled",
    "cron-schedule",
}


class ConfigError(ValueError):
    """Raised when knowledge-miner configuration is invalid."""


@dataclass
class KnowledgeMinerConfig:
    """knowledge-miner 配置"""

    # 数据源配置
    data_sources: list[str] = field(default_factory=lambda: ["claude", "hermes"])

    # Claude Code 配置
    claude_projects_dir: Path = field(
        default_factory=lambda: Path.home() / ".claude" / "projects"
    )

    # Hermes 配置
    hermes_sessions_dir: Path = field(
        default_factory=lambda: Path.home() / ".hermes" / "sessions"
    )

    # 输出配置
    output_path: Path = field(default_factory=lambda: _default_output_path())

    # 飞书配置
    feishu_enabled: bool = False
    feishu_space_id: str | None = None
    feishu_node_token: str | None = None

    # 分析配置
    analysis_granularity: str = "global"  # global, project, time
    content_priority: list[str] = field(
        default_factory=lambda: [
            "pitfalls",
            "thinking_patterns",
            "workflows",
            "communication_style",
        ]
    )

    # 触发配置
    cron_enabled: bool = False
    cron_schedule: str = "0 23 * * *"  # 每天 23:00

    def __post_init__(self) -> None:
        """Normalize user-provided config values after JSON/env loading."""
        if not isinstance(self.data_sources, list):
            raise ConfigError("data-sources 必须是列表")
        if not isinstance(self.content_priority, list):
            raise ConfigError("content-priority 必须是列表")
        self.data_sources = _normalize_string_list(self.data_sources, "data-sources")
        self.claude_projects_dir = _expand_path(self.claude_projects_dir)
        self.hermes_sessions_dir = _expand_path(self.hermes_sessions_dir)
        self.output_path = _expand_path(self.output_path)
        self.content_priority = _normalize_string_list(
            self.content_priority,
            "content-priority",
        )
        self.validate()

    @classmethod
    def from_env(cls) -> KnowledgeMinerConfig:
        """从环境变量加载配置"""
        config = cls()
        _apply_env_overrides(config)
        config.validate()
        return config

    @classmethod
    def from_file(cls, path: Path) -> KnowledgeMinerConfig:
        """从 JSON 文件加载配置"""
        with open(path) as f:
            data = json.load(f)
        unknown_keys = set(data) - CONFIG_FILE_KEYS
        if unknown_keys:
            raise ConfigError(f"配置文件包含未知字段: {', '.join(sorted(unknown_keys))}")
        return cls(**{k.replace("-", "_"): v for k, v in data.items()})

    def validate(self) -> None:
        """Validate normalized config values."""
        unknown_sources = sorted(set(self.data_sources) - VALID_DATA_SOURCES)
        if not self.data_sources:
            raise ConfigError("data-sources 不能为空")
        if unknown_sources:
            raise ConfigError(
                f"未知数据源: {', '.join(unknown_sources)}；支持: "
                f"{', '.join(sorted(VALID_DATA_SOURCES))}"
            )

        if self.analysis_granularity not in VALID_GRANULARITIES:
            raise ConfigError(
                f"analysis-granularity 必须是 "
                f"{'/'.join(sorted(VALID_GRANULARITIES))} 之一"
            )

        unknown_priorities = sorted(set(self.content_priority) - VALID_CONTENT_PRIORITIES)
        if not self.content_priority:
            raise ConfigError("content-priority 不能为空")
        if unknown_priorities:
            raise ConfigError(
                f"未知 content-priority: {', '.join(unknown_priorities)}；支持: "
                f"{', '.join(sorted(VALID_CONTENT_PRIORITIES))}"
            )

        if self.output_path.exists() and self.output_path.is_dir():
            raise ConfigError(f"output-path 不能是目录: {self.output_path}")

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "data-sources": self.data_sources,
            "claude-projects-dir": str(self.claude_projects_dir),
            "hermes-sessions-dir": str(self.hermes_sessions_dir),
            "output-path": str(self.output_path),
            "feishu-enabled": self.feishu_enabled,
            "feishu-space-id": self.feishu_space_id,
            "feishu-node-token": self.feishu_node_token,
            "analysis-granularity": self.analysis_granularity,
            "content-priority": self.content_priority,
            "cron-enabled": self.cron_enabled,
            "cron-schedule": self.cron_schedule,
        }

    def save(self, path: Path) -> None:
        """保存配置到文件"""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)


# 默认配置实例
_default_config: KnowledgeMinerConfig | None = None


def get_config() -> KnowledgeMinerConfig:
    """获取全局配置"""
    global _default_config
    if _default_config is None:
        config_path = Path.home() / ".knowledge-miner" / "config.json"
        if config_path.exists():
            _default_config = KnowledgeMinerConfig.from_file(config_path)
            _apply_env_overrides(_default_config)
        else:
            _default_config = KnowledgeMinerConfig.from_env()
    return _default_config


def set_config(config: KnowledgeMinerConfig) -> None:
    """设置全局配置"""
    global _default_config
    _default_config = config


def _apply_env_overrides(config: KnowledgeMinerConfig) -> None:
    """Apply KM_* environment variables on top of an existing config."""
    if os.getenv("KM_DATA_SOURCES"):
        config.data_sources = [
            source.strip()
            for source in os.getenv("KM_DATA_SOURCES", "").split(",")
            if source.strip()
        ]

    if os.getenv("KM_CLAUDE_DIR"):
        config.claude_projects_dir = _expand_path(os.getenv("KM_CLAUDE_DIR", ""))

    if os.getenv("KM_HERMES_DIR"):
        config.hermes_sessions_dir = _expand_path(os.getenv("KM_HERMES_DIR", ""))

    if os.getenv("KM_OUTPUT_PATH"):
        config.output_path = _expand_path(os.getenv("KM_OUTPUT_PATH", ""))

    if os.getenv("KM_FEISHU_ENABLED"):
        config.feishu_enabled = _parse_bool_env("KM_FEISHU_ENABLED")
    if os.getenv("KM_FEISHU_SPACE_ID"):
        config.feishu_space_id = os.getenv("KM_FEISHU_SPACE_ID")
    if os.getenv("KM_FEISHU_NODE_TOKEN"):
        config.feishu_node_token = os.getenv("KM_FEISHU_NODE_TOKEN")

    if os.getenv("KM_GRANULARITY"):
        config.analysis_granularity = os.getenv("KM_GRANULARITY", "global")
    if os.getenv("KM_PRIORITY"):
        config.content_priority = [
            item.strip()
            for item in os.getenv("KM_PRIORITY", "").split(",")
            if item.strip()
        ]

    if os.getenv("KM_CRON_ENABLED"):
        config.cron_enabled = _parse_bool_env("KM_CRON_ENABLED")
    if os.getenv("KM_CRON_SCHEDULE"):
        config.cron_schedule = os.getenv("KM_CRON_SCHEDULE", config.cron_schedule)
    config.validate()


def _parse_bool_env(name: str) -> bool:
    value = os.getenv(name, "").strip().lower()
    if value in {"1", "true", "yes", "y", "on"}:
        return True
    if value in {"0", "false", "no", "n", "off"}:
        return False
    raise ConfigError(f"环境变量 {name} 必须是布尔值 true/false/1/0/yes/no")


def _normalize_string_list(items: list[Any], field_name: str) -> list[str]:
    normalized: list[str] = []
    for item in items:
        if not isinstance(item, str):
            raise ConfigError(f"{field_name} 中的项目必须是字符串")
        value = item.strip()
        if value:
            normalized.append(value)
    return normalized


def _expand_path(value: str | Path) -> Path:
    """Expand a user-facing filesystem path without requiring it to exist."""
    try:
        return Path(value).expanduser()
    except TypeError as exc:
        raise ConfigError(f"路径配置必须是字符串或 Path: {value!r}") from exc


def _default_output_path() -> Path:
    """Prefer the user's AI-Knowledge-Base folder when it already exists."""
    ai_knowledge_base = Path.home() / "Desktop" / "AI-Knowledge-Base"
    if ai_knowledge_base.exists():
        return ai_knowledge_base / "knowledge-base.json"
    return Path.home() / "knowledge-base" / "knowledge.json"
