"""Feishu/Lark user authorization helpers."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

DEFAULT_FEISHU_SCOPES = (
    "docx:document:readonly docx:document:write_only "
    "wiki:node:read wiki:space:read offline_access"
)
PENDING_AUTH_FILENAME = "feishu-auth-pending.json"
QR_FILENAME = "feishu-auth-qr.png"


@dataclass
class FeishuAuthStart:
    """Pending Feishu device authorization."""

    verification_url: str
    device_code: str
    expires_in: int
    qrcode_path: Path
    scopes: str

    @property
    def expires_at(self) -> datetime:
        return datetime.now() + timedelta(seconds=self.expires_in)


class FeishuAuthManager:
    """Wrap lark-cli authorization commands for MCP tools."""

    def __init__(
        self,
        cli: str = "lark-cli",
        state_dir: Path | None = None,
    ) -> None:
        self.cli = cli
        self.state_dir = state_dir or Path.home() / ".knowledge-miner"

    def status(self) -> dict[str, Any]:
        self._ensure_cli()
        return self._run_json([self.cli, "auth", "status"])

    def start(self, scopes: str = DEFAULT_FEISHU_SCOPES) -> FeishuAuthStart:
        self._ensure_cli()
        self.state_dir.mkdir(parents=True, exist_ok=True)
        payload = self._run_json(
            [
                self.cli,
                "auth",
                "login",
                "--scope",
                scopes,
                "--no-wait",
                "--json",
            ]
        )
        verification_url = _required_payload_text(payload, "verification_url")
        device_code = _required_payload_text(payload, "device_code")
        expires_in = int(payload.get("expires_in") or 600)
        qrcode_path = self._write_qrcode(verification_url)
        self._write_pending(
            {
                "verification_url": verification_url,
                "device_code": device_code,
                "expires_in": expires_in,
                "scopes": scopes,
                "qrcode_path": str(qrcode_path),
                "created_at": datetime.now().isoformat(),
            }
        )
        return FeishuAuthStart(
            verification_url=verification_url,
            device_code=device_code,
            expires_in=expires_in,
            qrcode_path=qrcode_path,
            scopes=scopes,
        )

    def complete(self, device_code: str | None = None) -> dict[str, Any]:
        self._ensure_cli()
        code = device_code or self._read_pending_device_code()
        if not code:
            raise RuntimeError("没有待完成的飞书授权，请先调用 start_feishu_auth")
        payload = self._run_json(
            [self.cli, "auth", "login", "--device-code", code, "--json"]
        )
        self._clear_pending()
        return payload

    def _write_qrcode(self, verification_url: str) -> Path:
        self._run_jsonless(
            [
                self.cli,
                "auth",
                "qrcode",
                verification_url,
                "--output",
                QR_FILENAME,
            ],
            cwd=self.state_dir,
        )
        return self.state_dir / QR_FILENAME

    def _write_pending(self, payload: dict[str, Any]) -> None:
        (self.state_dir / PENDING_AUTH_FILENAME).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _read_pending_device_code(self) -> str | None:
        path = self.state_dir / PENDING_AUTH_FILENAME
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("device_code")

    def _clear_pending(self) -> None:
        path = self.state_dir / PENDING_AUTH_FILENAME
        if path.exists():
            path.unlink()

    def _run_json(self, argv: list[str]) -> dict[str, Any]:
        completed = self._run_jsonless(argv)
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"lark-cli 返回非 JSON 输出: {completed.stdout[:200]}") from exc
        return payload

    def _run_jsonless(
        self,
        argv: list[str],
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        completed = subprocess.run(
            argv,
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or completed.stdout.strip())
        return completed

    def _ensure_cli(self) -> None:
        if not shutil.which(self.cli):
            raise RuntimeError("未找到 lark-cli，请先安装 lark-cli 后再授权飞书")


def _required_payload_text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"lark-cli 输出缺少 {key}")
    return value
