"""Feishu/Lark user authorization helpers."""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
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
SETUP_STATE_FILENAME = "feishu-setup-pending.json"
SETUP_QR_FILENAME = "feishu-setup-qr.png"
SETUP_LOG_FILENAME = "feishu-setup.log"
SETUP_URL_FILENAME = "feishu-setup-url.txt"
SETUP_URL_PATTERN = re.compile(r"https://open\.(?:feishu\.cn|larksuite\.com)/\S+")
SETUP_HELPER_CODE = r"""
import os
import pty
import re
import select
import subprocess
import sys

cli, log_path, url_path = sys.argv[1:4]
pattern = re.compile(rb"https://open\.(?:feishu\.cn|larksuite\.com)/\S+")
master, slave = pty.openpty()
process = subprocess.Popen(
    [cli, "config", "init", "--new"],
    stdin=slave,
    stdout=slave,
    stderr=slave,
)
os.close(slave)
buffer = b""
url_written = False
with open(log_path, "ab", buffering=0) as log:
    while True:
        ready, _, _ = select.select([master], [], [], 0.2)
        if ready:
            try:
                data = os.read(master, 4096)
            except OSError:
                break
            if not data:
                break
            log.write(data)
            buffer = (buffer + data)[-12000:]
            if not url_written:
                match = pattern.search(buffer)
                if match:
                    with open(url_path, "wb") as url_file:
                        url_file.write(match.group(0).rstrip())
                    url_written = True
        if process.poll() is not None:
            break
sys.exit(process.poll() or 0)
"""


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


@dataclass
class FeishuSetupStart:
    """Pending lark-cli application setup."""

    setup_url: str
    qrcode_path: Path
    log_path: Path
    pid: int


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

    def start_setup(self, timeout_seconds: float = 10) -> FeishuSetupStart:
        self._ensure_cli()
        self.state_dir.mkdir(parents=True, exist_ok=True)
        log_path = self.state_dir / SETUP_LOG_FILENAME
        url_path = self.state_dir / SETUP_URL_FILENAME
        for path in (log_path, url_path):
            if path.exists():
                path.unlink()

        process = subprocess.Popen(
            [
                sys.executable,
                "-c",
                SETUP_HELPER_CODE,
                self.cli,
                str(log_path),
                str(url_path),
            ],
            cwd=self.state_dir,
            env=os.environ.copy(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        setup_url = self._wait_for_setup_url(
            log_path,
            url_path,
            process,
            timeout_seconds,
        )
        qrcode_path = self._write_qrcode(setup_url, SETUP_QR_FILENAME)
        self._write_setup_state(
            {
                "setup_url": setup_url,
                "qrcode_path": str(qrcode_path),
                "log_path": str(log_path),
                "pid": process.pid,
                "created_at": datetime.now().isoformat(),
            }
        )
        return FeishuSetupStart(
            setup_url=setup_url,
            qrcode_path=qrcode_path,
            log_path=log_path,
            pid=process.pid,
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

    def _write_qrcode(self, verification_url: str, filename: str = QR_FILENAME) -> Path:
        self._run_jsonless(
            [
                self.cli,
                "auth",
                "qrcode",
                verification_url,
                "--output",
                filename,
            ],
            cwd=self.state_dir,
        )
        return self.state_dir / filename

    def _write_pending(self, payload: dict[str, Any]) -> None:
        (self.state_dir / PENDING_AUTH_FILENAME).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _write_setup_state(self, payload: dict[str, Any]) -> None:
        (self.state_dir / SETUP_STATE_FILENAME).write_text(
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

    def _wait_for_setup_url(
        self,
        log_path: Path,
        url_path: Path,
        process: subprocess.Popen[bytes],
        timeout_seconds: float,
    ) -> str:
        deadline = time.time() + timeout_seconds
        last_text = ""
        while time.time() < deadline:
            if url_path.exists():
                return url_path.read_text(encoding="utf-8").strip()
            if log_path.exists():
                last_text = log_path.read_text(encoding="utf-8", errors="replace")
                match = SETUP_URL_PATTERN.search(last_text)
                if match:
                    return match.group(0).rstrip()
            if process.poll() is not None:
                break
            time.sleep(0.2)
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
        raise RuntimeError(f"未能获取 lark-cli 首次配置 URL: {last_text[-500:]}")


def _required_payload_text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"lark-cli 输出缺少 {key}")
    return value


def is_lark_cli_not_configured(error: Exception) -> bool:
    text = str(error)
    return '"subtype": "not_configured"' in text or "not_configured" in text
