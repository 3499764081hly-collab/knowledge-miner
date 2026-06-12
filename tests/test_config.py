import json
from pathlib import Path

import pytest

from knowledge_miner import config as config_module
from knowledge_miner.config import (
    ConfigError,
    KnowledgeMinerConfig,
    _default_output_path,
    get_config,
)


def test_config_from_file_normalizes_paths(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    output_path = tmp_path / "knowledge.json"
    config_path.write_text(
        json.dumps(
            {
                "data-sources": ["claude", " hermes "],
                "claude-projects-dir": str(tmp_path / "claude"),
                "hermes-sessions-dir": str(tmp_path / "hermes"),
                "output-path": str(output_path),
                "feishu-doc-url": "https://my.feishu.cn/wiki/example",
                "content-priority": ["pitfalls", " workflows "],
            }
        ),
        encoding="utf-8",
    )

    config = KnowledgeMinerConfig.from_file(config_path)

    assert config.data_sources == ["claude", "hermes"]
    assert config.claude_projects_dir == tmp_path / "claude"
    assert config.hermes_sessions_dir == tmp_path / "hermes"
    assert config.output_path == output_path
    assert config.feishu_doc_url == "https://my.feishu.cn/wiki/example"
    assert config.content_priority == ["pitfalls", "workflows"]


def test_config_from_file_rejects_unknown_keys(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"data-sources": ["claude"], "surprise": True}),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="未知字段"):
        KnowledgeMinerConfig.from_file(config_path)


@pytest.mark.parametrize(
    "payload, message",
    [
        ({"data-sources": ["claude", "cursor"]}, "未知数据源"),
        ({"data-sources": []}, "不能为空"),
        ({"content-priority": ["pitfalls", "unknown"]}, "content-priority"),
        ({"analysis-granularity": "session"}, "analysis-granularity"),
        ({"data-sources": ["claude", 1]}, "必须是字符串"),
    ],
)
def test_config_rejects_invalid_values(payload: dict, message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        KnowledgeMinerConfig(**{key.replace("-", "_"): value for key, value in payload.items()})


def test_config_rejects_output_path_directory(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="不能是目录"):
        KnowledgeMinerConfig(output_path=tmp_path)


def test_get_config_applies_env_overrides_to_config_file(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config_dir = tmp_path / ".knowledge-miner"
    config_dir.mkdir()
    (config_dir / "config.json").write_text(
        json.dumps(
            {
                "data-sources": ["claude"],
                "claude-projects-dir": str(tmp_path / "file-claude"),
                "hermes-sessions-dir": str(tmp_path / "file-hermes"),
                "output-path": str(tmp_path / "file-output.json"),
            }
        ),
        encoding="utf-8",
    )
    env_hermes = tmp_path / "env-hermes"
    env_output = tmp_path / "env-output.json"
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(config_module, "_default_config", None)
    monkeypatch.setenv("KM_DATA_SOURCES", "hermes")
    monkeypatch.setenv("KM_HERMES_DIR", str(env_hermes))
    monkeypatch.setenv("KM_OUTPUT_PATH", str(env_output))
    monkeypatch.setenv("KM_FEISHU_DOC_URL", "https://my.feishu.cn/wiki/env-doc")

    config = get_config()

    assert config.data_sources == ["hermes"]
    assert config.claude_projects_dir == tmp_path / "file-claude"
    assert config.hermes_sessions_dir == env_hermes
    assert config.output_path == env_output
    assert config.feishu_doc_url == "https://my.feishu.cn/wiki/env-doc"


def test_get_config_validates_env_overrides(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(config_module, "_default_config", None)
    monkeypatch.setenv("KM_DATA_SOURCES", "claude,cursor")

    with pytest.raises(ConfigError, match="未知数据源"):
        get_config()


def test_config_bool_env_accepts_yes_no(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(config_module, "_default_config", None)
    monkeypatch.setenv("KM_FEISHU_ENABLED", "yes")
    monkeypatch.setenv("KM_CRON_ENABLED", "0")

    config = get_config()

    assert config.feishu_enabled is True
    assert config.cron_enabled is False


def test_config_bool_env_rejects_invalid_value(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(config_module, "_default_config", None)
    monkeypatch.setenv("KM_FEISHU_ENABLED", "maybe")

    with pytest.raises(ConfigError, match="KM_FEISHU_ENABLED"):
        get_config()


def test_config_save_creates_parent_directory(tmp_path: Path) -> None:
    config_path = tmp_path / "nested" / "config.json"

    KnowledgeMinerConfig(output_path=tmp_path / "knowledge.json").save(config_path)

    assert config_path.exists()


def test_default_output_path_prefers_ai_knowledge_base(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    ai_base = tmp_path / "Desktop" / "AI-Knowledge-Base"
    ai_base.mkdir(parents=True)

    assert _default_output_path() == ai_base / "knowledge-base.json"
