import sys

import pytest

from knowledge_miner import cli as cli_module
from knowledge_miner import config as config_module
from knowledge_miner.cli import _normalize_argv, create_parser
from knowledge_miner.cli import main as cli_main
from knowledge_miner.config import KnowledgeMinerConfig


def test_knowledge_mine_entrypoint_defaults_to_mine(monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["knowledge-mine", "--days", "30", "--source", "claude"])

    assert _normalize_argv() == ["mine", "--days", "30", "--source", "claude"]


def test_knowledge_miner_entrypoint_keeps_explicit_command(monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["knowledge-miner", "read", "--format", "json"])

    assert _normalize_argv() == ["read", "--format", "json"]


def test_knowledge_mine_entrypoint_keeps_doctor_command(monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["knowledge-mine", "doctor"])

    assert _normalize_argv() == ["doctor"]


def test_parser_accepts_knowledge_mine_shortcut(monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["knowledge-mine", "--days", "2", "--dry-run", "--yes"])

    args = create_parser().parse_args(_normalize_argv())

    assert args.command == "mine"
    assert args.days == 2
    assert args.dry_run is True
    assert args.yes is True


def test_parser_accepts_doctor_command() -> None:
    args = create_parser().parse_args(["doctor"])

    assert args.command == "doctor"


def test_parser_accepts_doctor_mcp_smoke() -> None:
    args = create_parser().parse_args(["doctor", "--mcp-smoke"])

    assert args.command == "doctor"
    assert args.mcp_smoke is True


def test_parser_accepts_doctor_acceptance() -> None:
    args = create_parser().parse_args(["doctor", "--acceptance"])

    assert args.command == "doctor"
    assert args.acceptance is True


def test_parser_accepts_config_mcp_json() -> None:
    args = create_parser().parse_args(["config", "--mcp-json"])

    assert args.command == "config"
    assert args.mcp_json is True


def test_parser_rejects_unimplemented_mcp_sse_transport() -> None:
    with pytest.raises(SystemExit):
        create_parser().parse_args(["mcp-server", "--transport", "sse"])


def test_main_exits_cleanly_for_config_errors(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    monkeypatch.setattr(config_module, "_default_config", None)
    monkeypatch.setenv("KM_DATA_SOURCES", "cursor")

    with pytest.raises(SystemExit) as exc:
        cli_main(["doctor"])

    assert exc.value.code == 2


def test_doctor_mcp_smoke_runs_optional_check(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    monkeypatch.setattr(config_module, "_default_config", None)
    (tmp_path / "Desktop" / "AI-Knowledge-Base").mkdir(parents=True)
    called = {"value": False}

    def fake_smoke() -> tuple[bool, str]:
        called["value"] = True
        return True, "knowledge-miner: mine_knowledge, get_knowledge, get_stats"

    monkeypatch.setattr(cli_module, "_run_mcp_smoke_check", fake_smoke)

    cli_main(["doctor", "--mcp-smoke"])

    assert called["value"] is True


def test_doctor_acceptance_runs_optional_check(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    monkeypatch.setattr(config_module, "_default_config", None)
    (tmp_path / "Desktop" / "AI-Knowledge-Base").mkdir(parents=True)
    called = {"value": False}

    def fake_acceptance() -> tuple[bool, str]:
        called["value"] = True
        return True, "临时数据预览、确认写入、统计读取均通过"

    monkeypatch.setattr(cli_module, "_run_mcp_acceptance_check", fake_acceptance)

    cli_main(["doctor", "--acceptance"])

    assert called["value"] is True


def test_build_mcp_config_json_uses_current_config(monkeypatch, tmp_path) -> None:
    command_path = tmp_path / "knowledge-miner"
    command_path.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", [str(command_path)])
    output_path = tmp_path / "knowledge-base.json"
    config = KnowledgeMinerConfig(data_sources=["claude"], output_path=output_path)

    data = cli_module._build_mcp_config_json(config)

    server = data["mcpServers"]["knowledge-miner"]
    assert server["command"] == str(command_path)
    assert server["args"] == ["mcp-server"]
    assert server["env"] == {
        "KM_DATA_SOURCES": "claude",
        "KM_OUTPUT_PATH": str(output_path),
    }


def test_build_mcp_config_json_includes_feishu_env(monkeypatch, tmp_path) -> None:
    command_path = tmp_path / "knowledge-miner"
    command_path.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", [str(command_path)])
    config = KnowledgeMinerConfig(
        output_path=tmp_path / "knowledge-base.json",
        feishu_enabled=True,
        feishu_doc_url="https://my.feishu.cn/wiki/example",
    )

    data = cli_module._build_mcp_config_json(config)

    assert data["mcpServers"]["knowledge-miner"]["env"]["KM_FEISHU_ENABLED"] == "true"
    assert (
        data["mcpServers"]["knowledge-miner"]["env"]["KM_FEISHU_DOC_URL"]
        == "https://my.feishu.cn/wiki/example"
    )
