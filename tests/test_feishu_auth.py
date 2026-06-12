import json
import subprocess
from pathlib import Path

import pytest

from knowledge_miner import feishu_auth
from knowledge_miner.feishu_auth import FeishuAuthManager


def test_feishu_auth_start_returns_url_and_writes_pending(
    monkeypatch,
    tmp_path: Path,
) -> None:
    calls: list[tuple[list[str], Path | None]] = []

    def fake_run(
        argv: list[str],
        cwd: Path | None = None,
        check: bool = False,
        capture_output: bool = True,
        text: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        calls.append((argv, cwd))
        if argv[:3] == ["lark-cli", "auth", "login"]:
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout=json.dumps(
                    {
                        "verification_url": "https://passport.feishu.cn/device",
                        "device_code": "device-123",
                        "expires_in": 600,
                    }
                ),
                stderr="",
            )
        if argv[:3] == ["lark-cli", "auth", "qrcode"]:
            assert cwd == tmp_path
            (tmp_path / feishu_auth.QR_FILENAME).write_bytes(b"png")
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        raise AssertionError(f"unexpected command: {argv}")

    monkeypatch.setattr(feishu_auth.shutil, "which", lambda cli: "/usr/bin/lark-cli")
    monkeypatch.setattr(feishu_auth.subprocess, "run", fake_run)

    auth = FeishuAuthManager(state_dir=tmp_path).start(scopes="scope-a")

    pending = json.loads(
        (tmp_path / feishu_auth.PENDING_AUTH_FILENAME).read_text(encoding="utf-8")
    )
    assert auth.verification_url == "https://passport.feishu.cn/device"
    assert auth.device_code == "device-123"
    assert auth.qrcode_path == tmp_path / feishu_auth.QR_FILENAME
    assert pending["device_code"] == "device-123"
    assert pending["scopes"] == "scope-a"
    assert calls[0][0] == [
        "lark-cli",
        "auth",
        "login",
        "--scope",
        "scope-a",
        "--no-wait",
        "--json",
    ]
    assert calls[1][0][:3] == ["lark-cli", "auth", "qrcode"]


def test_feishu_auth_complete_uses_pending_code_and_clears_cache(
    monkeypatch,
    tmp_path: Path,
) -> None:
    pending_path = tmp_path / feishu_auth.PENDING_AUTH_FILENAME
    pending_path.write_text(
        json.dumps({"device_code": "device-123"}),
        encoding="utf-8",
    )
    calls: list[list[str]] = []

    def fake_run(
        argv: list[str],
        cwd: Path | None = None,
        check: bool = False,
        capture_output: bool = True,
        text: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=json.dumps({"ok": True}),
            stderr="",
        )

    monkeypatch.setattr(feishu_auth.shutil, "which", lambda cli: "/usr/bin/lark-cli")
    monkeypatch.setattr(feishu_auth.subprocess, "run", fake_run)

    payload = FeishuAuthManager(state_dir=tmp_path).complete()

    assert payload == {"ok": True}
    assert calls == [
        ["lark-cli", "auth", "login", "--device-code", "device-123", "--json"]
    ]
    assert not pending_path.exists()


def test_feishu_auth_missing_cli_returns_actionable_error(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(feishu_auth.shutil, "which", lambda cli: None)

    with pytest.raises(RuntimeError, match="未找到 lark-cli"):
        FeishuAuthManager(state_dir=tmp_path).status()


def test_feishu_auth_rejects_missing_device_code(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(feishu_auth.shutil, "which", lambda cli: "/usr/bin/lark-cli")

    with pytest.raises(RuntimeError, match="请先调用 start_feishu_auth"):
        FeishuAuthManager(state_dir=tmp_path).complete()
