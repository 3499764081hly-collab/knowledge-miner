"""CLI 接口模块"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from knowledge_miner import __version__
from knowledge_miner.config import ConfigError, KnowledgeMinerConfig, get_config
from knowledge_miner.miner import MiningResult, mine_knowledge
from knowledge_miner.models import KnowledgeBase
from knowledge_miner.output.ai_knowledge_base import extract_agent_view
from knowledge_miner.output.json_writer import JsonWriter

console = Console()
stderr_console = Console(stderr=True)
COMMANDS = {"mine", "read", "stats", "config", "doctor", "mcp-server"}


def create_parser() -> argparse.ArgumentParser:
    """创建参数解析器"""
    parser = argparse.ArgumentParser(
        prog="knowledge-miner",
        description="从 AI agent 聊天记录中沉淀个人知识库",
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # mine 子命令
    mine_parser = subparsers.add_parser("mine", help="触发知识沉淀")
    mine_parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="分析最近 N 天的会话（默认 7）",
    )
    mine_parser.add_argument(
        "--source",
        choices=["claude", "hermes", "all"],
        default="all",
        help="数据源（默认 all）",
    )
    mine_parser.add_argument(
        "--output",
        type=Path,
        help="输出路径（默认使用配置中的 output-path）",
    )
    mine_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只预览将写入的内容，不修改知识库文件",
    )
    mine_parser.add_argument(
        "--yes",
        action="store_true",
        help="确认写入知识库文件；未指定时只预览不写入",
    )

    # read 子命令
    read_parser = subparsers.add_parser("read", help="读取知识库")
    read_parser.add_argument(
        "--section",
        choices=["all", "pitfalls", "thinking", "workflows", "communication"],
        default="all",
        help="读取特定部分（默认 all）",
    )
    read_parser.add_argument(
        "--format",
        choices=["json", "table", "markdown"],
        default="table",
        help="输出格式（默认 table）",
    )

    # stats 子命令
    subparsers.add_parser("stats", help="查看统计信息")

    # doctor 子命令
    doctor_parser = subparsers.add_parser("doctor", help="检查数据源、输出路径和 MCP Server 可用性")
    doctor_parser.add_argument(
        "--mcp-smoke",
        action="store_true",
        help="真实启动 stdio MCP Server 并检查握手和工具列表",
    )
    doctor_parser.add_argument(
        "--acceptance",
        action="store_true",
        help="用临时数据运行 stdio MCP 端到端验收，不触碰真实知识库",
    )

    # config 子命令
    config_parser = subparsers.add_parser("config", help="配置管理")
    config_parser.add_argument(
        "--init",
        action="store_true",
        help="初始化配置文件",
    )
    config_parser.add_argument(
        "--show",
        action="store_true",
        help="显示当前配置",
    )
    config_parser.add_argument(
        "--mcp-json",
        action="store_true",
        help="输出可复制到 Claude/Codex 的 MCP Server 配置 JSON",
    )

    # mcp-server 子命令
    mcp_parser = subparsers.add_parser("mcp-server", help="启动 MCP Server")
    mcp_parser.add_argument(
        "--transport",
        choices=["stdio"],
        default="stdio",
        help="传输方式（当前支持 stdio，默认 stdio）",
    )

    return parser


def cmd_mine(args: argparse.Namespace) -> None:
    """执行知识沉淀"""
    config = get_config()
    output_path = args.output or config.output_path

    console.print(Panel.fit(
        f"[bold blue]知识沉淀分析[/bold blue]\n"
        f"数据源: {args.source}\n"
        f"时间范围: 最近 {args.days} 天\n"
        f"输出路径: {output_path}\n"
        f"模式: {'dry-run 预览' if args.dry_run or not args.yes else '写入'}",
        title="knowledge-miner",
    ))

    result = mine_knowledge(
        days=args.days,
        source=args.source,
        output_path=output_path,
        config=config,
    )

    if not result.messages or not result.knowledge_base:
        console.print("[yellow]没有找到任何消息，请检查数据源配置[/yellow]")
        return

    console.print(f"\n共提取 [bold]{len(result.messages)}[/bold] 条消息")

    if args.dry_run:
        _print_preview(result)
        return

    if not args.yes:
        console.print("[yellow]未指定 --yes，已改为预览模式，未写入任何文件。[/yellow]")
        _print_preview(result)
        return

    writer = JsonWriter(result.output_path)
    writer.write(result.knowledge_base)

    console.print(f"\n✓ 知识库已保存到: [bold]{result.output_path}[/bold]")
    if writer.last_backup_path:
        console.print(f"✓ 写入前备份: [bold]{writer.last_backup_path}[/bold]")

    # 显示摘要
    _print_summary(result.knowledge_base)


def cmd_read(args: argparse.Namespace) -> None:
    """读取知识库"""
    config = get_config()
    output_path = config.output_path

    writer = JsonWriter(output_path)
    data = writer.read()

    if not data:
        console.print("[yellow]知识库不存在，请先运行 'knowledge-miner mine'[/yellow]")
        return

    data = extract_agent_view(data)
    section = args.section
    fmt = args.format

    if fmt == "json":
        console.print_json(data=data)
    elif fmt == "markdown":
        _print_markdown(data, section)
    else:
        _print_table(data, section)


def cmd_stats(args: argparse.Namespace) -> None:
    """查看统计信息"""
    config = get_config()
    output_path = config.output_path

    writer = JsonWriter(output_path)
    data = writer.read()

    if not data:
        console.print("[yellow]知识库不存在，请先运行 'knowledge-miner mine'[/yellow]")
        return

    data = extract_agent_view(data)
    meta = data.get("metadata", {})
    pitfalls = data.get("pitfalls", {}).get("items", [])
    patterns = data.get("thinking_patterns", {}).get("items", [])
    workflows = data.get("workflows", {}).get("items", [])

    table = Table(title="知识库统计")
    table.add_column("指标", style="cyan")
    table.add_column("值", style="green")

    table.add_row("版本", meta.get("version", "unknown"))
    table.add_row("生成时间", meta.get("generated_at", "unknown"))
    table.add_row("数据源", ", ".join(meta.get("sources", [])))
    table.add_row("总会话数", str(meta.get("total_sessions", 0)))
    table.add_row("总消息数", str(meta.get("total_messages", 0)))
    table.add_row("踩坑数量", str(len(pitfalls)))
    table.add_row("思维模式数量", str(len(patterns)))
    table.add_row("工作流数量", str(len(workflows)))

    console.print(table)


def cmd_doctor(args: argparse.Namespace) -> None:
    """检查本地运行环境"""
    config = get_config()

    table = Table(title="knowledge-miner 环境检查")
    table.add_column("检查项", style="cyan")
    table.add_column("状态", style="green")
    table.add_column("详情")

    checks = [
        (
            "Claude Code 数据目录",
            config.claude_projects_dir.exists(),
            str(config.claude_projects_dir),
        ),
        (
            "Hermes 数据目录",
            config.hermes_sessions_dir.exists(),
            str(config.hermes_sessions_dir),
        ),
        (
            "输出目录",
            config.output_path.parent.exists(),
            str(config.output_path.parent),
        ),
        (
            "当前 Python",
            Path(sys.executable).exists(),
            sys.executable,
        ),
    ]

    try:
        from knowledge_miner.mcp_server import server

        mcp_ok = server.name == "knowledge-miner"
        mcp_detail = "MCP Server 可加载"
    except Exception as exc:
        mcp_ok = False
        mcp_detail = f"MCP Server 加载失败: {exc}"

    checks.append(("MCP Server", mcp_ok, mcp_detail))

    if args.mcp_smoke:
        smoke_ok, smoke_detail = _run_mcp_smoke_check()
        checks.append(("MCP stdio 握手", smoke_ok, smoke_detail))

    if args.acceptance:
        acceptance_ok, acceptance_detail = _run_mcp_acceptance_check()
        checks.append(("MCP 端到端验收", acceptance_ok, acceptance_detail))

    for name, ok, detail in checks:
        table.add_row(name, "OK" if ok else "WARN", detail)

    console.print(table)
    console.print(
        "\n[yellow]提示：mine 默认只预览；真实写入需加 --yes，MCP 需 confirm_write=true。[/yellow]"
    )


def _run_mcp_smoke_check() -> tuple[bool, str]:
    """Start this package as a stdio MCP server and list its tools."""

    async def _smoke() -> tuple[bool, str]:
        from mcp import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client

        env = os.environ.copy()
        env["PYTHONPATH"] = _pythonpath_with_src(env)
        server_params = StdioServerParameters(
            command=sys.executable,
            args=["-c", "from knowledge_miner.cli import main; main(['mcp-server'])"],
            cwd=Path(__file__).resolve().parents[2],
            env=env,
        )
        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                init = await session.initialize()
                tools = await session.list_tools()

        tool_names = [tool.name for tool in tools.tools]
        expected = ["mine_knowledge", "get_knowledge", "get_stats"]
        missing = [name for name in expected if name not in tool_names]
        if missing:
            return False, f"缺少工具: {', '.join(missing)}"
        return True, f"{init.serverInfo.name}: {', '.join(tool_names)}"

    try:
        return asyncio.run(_smoke())
    except Exception as exc:
        return False, f"stdio 冒烟失败: {exc}"


def _run_mcp_acceptance_check() -> tuple[bool, str]:
    """Run a self-contained stdio MCP acceptance flow with temporary data."""

    async def _acceptance() -> tuple[bool, str]:
        from mcp import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client

        with tempfile.TemporaryDirectory(prefix="knowledge-miner-acceptance-") as tmp:
            tmp_path = Path(tmp)
            sessions_dir = tmp_path / "hermes"
            sessions_dir.mkdir()
            output_path = tmp_path / "knowledge-base.json"
            timestamp = datetime.now().isoformat(timespec="seconds")
            (sessions_dir / "acceptance.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "role": "user",
                                "timestamp": timestamp,
                                "content": "为什么 pytest 报错？",
                            },
                            ensure_ascii=False,
                        ),
                        json.dumps(
                            {
                                "role": "assistant",
                                "timestamp": timestamp,
                                "content": "失败: pytest 断言失败\n修复: 更新测试期望",
                            },
                            ensure_ascii=False,
                        ),
                    ]
                ),
                encoding="utf-8",
            )

            env = os.environ.copy()
            env.update(
                {
                    "KM_DATA_SOURCES": "hermes",
                    "KM_HERMES_DIR": str(sessions_dir),
                    "KM_OUTPUT_PATH": str(output_path),
                    "PYTHONPATH": _pythonpath_with_src(env),
                }
            )
            server_params = StdioServerParameters(
                command=sys.executable,
                args=["-c", "from knowledge_miner.cli import main; main(['mcp-server'])"],
                cwd=Path(__file__).resolve().parents[2],
                env=env,
            )
            async with stdio_client(server_params) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    tool_names = [tool.name for tool in tools.tools]
                    expected = ["mine_knowledge", "get_knowledge", "get_stats"]
                    missing = [name for name in expected if name not in tool_names]
                    if missing:
                        return False, f"缺少工具: {', '.join(missing)}"

                    preview = await session.call_tool(
                        "mine_knowledge",
                        {"source": "hermes", "days": 30},
                    )
                    if output_path.exists():
                        return False, "未确认写入时创建了知识库文件"
                    if "未提供 confirm_write=true" not in preview.content[0].text:
                        return False, "默认预览提示不符合预期"

                    written = await session.call_tool(
                        "mine_knowledge",
                        {"source": "hermes", "days": 30, "confirm_write": True},
                    )
                    if not output_path.exists():
                        return False, "确认写入后未生成知识库文件"
                    if "知识沉淀完成" not in written.content[0].text:
                        return False, "确认写入返回内容不符合预期"

                    stats = await session.call_tool("get_stats", {})
                    if "total_messages" not in stats.content[0].text:
                        return False, "写入后 get_stats 未返回统计信息"

        return True, "临时数据预览、确认写入、统计读取均通过"

    try:
        return asyncio.run(_acceptance())
    except Exception as exc:
        return False, f"端到端验收失败: {exc}"


def _pythonpath_with_src(env: dict[str, str]) -> str:
    src = str(Path(__file__).resolve().parents[2] / "src")
    existing = env.get("PYTHONPATH")
    if not existing:
        return src
    return f"{src}{os.pathsep}{existing}"


def cmd_config(args: argparse.Namespace) -> None:
    """配置管理"""
    config_dir = Path.home() / ".knowledge-miner"
    config_path = config_dir / "config.json"

    if args.init:
        config_dir.mkdir(parents=True, exist_ok=True)
        config = KnowledgeMinerConfig()
        config.save(config_path)
        console.print(f"✓ 配置文件已创建: {config_path}")
        console.print("请编辑配置文件设置数据源路径和其他参数")
    elif args.show:
        if config_path.exists():
            with open(config_path) as f:
                console.print_json(data=json.load(f))
        else:
            console.print(
                "[yellow]配置文件不存在，运行 'knowledge-miner config --init' 创建[/yellow]"
            )
    elif args.mcp_json:
        config = get_config()
        console.print_json(data=_build_mcp_config_json(config))
    else:
        console.print("请指定 --init、--show 或 --mcp-json")


def _build_mcp_config_json(config: KnowledgeMinerConfig) -> dict:
    return {
        "mcpServers": {
            "knowledge-miner": {
                "command": _resolve_command_path(),
                "args": ["mcp-server"],
                "env": {
                    "KM_DATA_SOURCES": ",".join(config.data_sources),
                    "KM_OUTPUT_PATH": str(config.output_path),
                },
            }
        }
    }


def _resolve_command_path() -> str:
    argv0 = Path(sys.argv[0]).expanduser()
    if argv0.exists() and (argv0.is_absolute() or argv0.parent != Path(".")):
        return str(argv0.resolve())
    return shutil.which("knowledge-miner") or "knowledge-miner"


def cmd_mcp_server(args: argparse.Namespace) -> None:
    """启动 MCP Server"""
    from knowledge_miner.mcp_server import run_server

    try:
        asyncio.run(run_server(transport=args.transport))
    except KeyboardInterrupt:
        stderr_console.print("\n[yellow]服务器已停止[/yellow]")


def _print_summary(kb: KnowledgeBase) -> None:
    """打印知识库摘要"""
    pitfalls = kb.pitfalls.get("items", [])
    patterns = kb.thinking_patterns.get("items", [])
    workflows = kb.workflows.get("items", [])

    table = Table(title="知识沉淀摘要")
    table.add_column("类别", style="cyan")
    table.add_column("数量", style="green", justify="right")
    table.add_column("优先级", style="yellow", justify="center")

    table.add_row("⚠️ 踩过的坑", str(len(pitfalls)), "A")
    table.add_row("🧠 思维方式", str(len(patterns)), "B")
    table.add_row("🔄 工作流", str(len(workflows)), "C")
    table.add_row("💬 沟通风格", "1", "D")

    console.print(table)


def _print_preview(result: MiningResult) -> None:
    """打印 dry-run 预览摘要"""
    preview = result.preview
    counts = preview.get("knowledge_counts", {})
    storage = preview.get("storage", {})

    table = Table(title="Dry-run 预览")
    table.add_column("项目", style="cyan")
    table.add_column("值", style="green")
    table.add_row("输出路径", preview.get("output_path", str(result.output_path)))
    table.add_row("消息数", str(len(result.messages)))
    table.add_row("会话数", str(result.session_count))
    table.add_row("踩坑", str(counts.get("pitfalls", 0)))
    table.add_row("思维模式", str(counts.get("thinking_patterns", 0)))
    table.add_row("工作流", str(counts.get("workflows", 0)))
    table.add_row("预计新增", str(storage.get("would_add")))
    table.add_row("预计合并", str(storage.get("would_merge")))
    console.print(table)

    diagnostics = preview.get("extraction_diagnostics", [])
    if diagnostics:
        diagnostic_table = Table(title="解析诊断")
        diagnostic_table.add_column("数据源", style="cyan")
        diagnostic_table.add_column("文件", justify="right")
        diagnostic_table.add_column("成功", justify="right")
        diagnostic_table.add_column("空/无消息", justify="right")
        diagnostic_table.add_column("时间过滤", justify="right")
        diagnostic_table.add_column("坏行", justify="right")
        diagnostic_table.add_column("坏消息", justify="right")
        diagnostic_table.add_column("文件错误", justify="right")
        for diagnostic in diagnostics:
            diagnostic_table.add_row(
                diagnostic.get("source", ""),
                str(diagnostic.get("files_seen", 0)),
                str(diagnostic.get("files_parsed", 0)),
                str(diagnostic.get("files_empty", 0)),
                str(diagnostic.get("files_skipped_since", 0)),
                str(diagnostic.get("bad_lines", 0)),
                str(diagnostic.get("bad_messages", 0)),
                str(len(diagnostic.get("file_errors", []))),
            )
        console.print(diagnostic_table)

    categories = storage.get("categories", {})
    if categories:
        category_table = Table(title="分类写入预览")
        category_table.add_column("分类", style="cyan")
        category_table.add_column("待写入", justify="right")
        category_table.add_column("新增", justify="right")
        category_table.add_column("合并", justify="right")
        for category, values in categories.items():
            category_table.add_row(
                category,
                str(values.get("incoming", 0)),
                str(values.get("would_add", 0)),
                str(values.get("would_merge", 0)),
            )
        console.print(category_table)

    preserved = storage.get("preserved", {})
    if preserved:
        preserved_table = Table(title="保留结构")
        preserved_table.add_column("类型", style="cyan")
        preserved_table.add_column("字段/分类", style="green")
        preserved_table.add_row(
            "未知顶层字段",
            ", ".join(preserved.get("unknown_top_level_fields", [])) or "-",
        )
        preserved_table.add_row(
            "自定义分类",
            ", ".join(preserved.get("unknown_categories", [])) or "-",
        )
        console.print(preserved_table)

    samples = storage.get("samples", [])
    if samples:
        sample_table = Table(title="预览明细（前 10 条）")
        sample_table.add_column("动作", style="yellow")
        sample_table.add_column("分类", style="cyan")
        sample_table.add_column("标题", style="green")
        sample_table.add_column("摘要")
        for sample in samples[:10]:
            sample_table.add_row(
                "合并" if sample.get("operation") == "merge" else "新增",
                sample.get("category", ""),
                sample.get("title", "")[:36],
                sample.get("summary", "")[:80],
            )
        console.print(sample_table)

    console.print("[yellow]dry-run 模式未写入任何文件[/yellow]")


def _print_table(data: dict, section: str) -> None:
    """以表格格式输出"""
    if section == "all" or section == "pitfalls":
        items = data.get("pitfalls", {}).get("items", [])
        if items:
            table = Table(title="⚠️ 踩过的坑")
            table.add_column("ID", style="dim")
            table.add_column("类别", style="cyan")
            table.add_column("错误", style="red")
            table.add_column("修复", style="green")
            table.add_column("频率", justify="right")

            for item in items[:10]:
                table.add_row(
                    item.get("id", ""),
                    item.get("category", ""),
                    item.get("mistake", "")[:50],
                    item.get("fix", "")[:50],
                    str(item.get("frequency", 0)),
                )
            console.print(table)

    if section == "all" or section == "thinking":
        items = data.get("thinking_patterns", {}).get("items", [])
        if items:
            table = Table(title="🧠 思维方式")
            table.add_column("ID", style="dim")
            table.add_column("名称", style="cyan")
            table.add_column("描述", style="green")

            for item in items[:10]:
                table.add_row(
                    item.get("id", ""),
                    item.get("name", ""),
                    item.get("description", "")[:80],
                )
            console.print(table)


def _print_markdown(data: dict, section: str) -> None:
    """以 Markdown 格式输出"""
    if section in ("all", "pitfalls"):
        items = data.get("pitfalls", {}).get("items", [])
        if items:
            print("\n## ⚠️ 踩过的坑\n")
            for item in items:
                print(f"### {item.get('category', 'Unknown')}")
                print(f"- **错误**: {item.get('mistake', '')}")
                print(f"- **修复**: {item.get('fix', '')}")
                print(f"- **频率**: {item.get('frequency', 0)}")
                print()

    if section in ("all", "thinking"):
        items = data.get("thinking_patterns", {}).get("items", [])
        if items:
            print("\n## 🧠 思维方式\n")
            for item in items:
                print(f"### {item.get('name', 'Unknown')}")
                print(f"- **描述**: {item.get('description', '')}")
                print(f"- **频率**: {item.get('frequency', 0)}")
                print()


def _normalize_argv(argv: list[str] | None = None) -> list[str]:
    """Make the knowledge-mine entrypoint behave like a direct mine command."""
    normalized = list(sys.argv[1:] if argv is None else argv)
    program = Path(sys.argv[0]).name
    if program == "knowledge-mine" and (
        not normalized or normalized[0] not in COMMANDS
    ):
        normalized.insert(0, "mine")
    return normalized


def main(argv: list[str] | None = None) -> None:
    """主入口"""
    parser = create_parser()
    args = parser.parse_args(_normalize_argv(argv))

    if not args.command:
        parser.print_help()
        return

    commands = {
        "mine": cmd_mine,
        "read": cmd_read,
        "stats": cmd_stats,
        "doctor": cmd_doctor,
        "config": cmd_config,
        "mcp-server": cmd_mcp_server,
    }

    handler = commands.get(args.command)
    if handler:
        try:
            handler(args)
        except ConfigError as exc:
            stderr_console.print(f"[red]配置错误: {exc}[/red]")
            raise SystemExit(2) from exc
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
