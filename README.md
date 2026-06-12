# knowledge-miner

从 AI agent 聊天记录中沉淀个人知识库的本地 MCP 工具。

当前项目面向 `/Users/Zhuanz1/Desktop/AI-Knowledge-Base/knowledge-base.json`，把 Claude Code / Hermes 等 agent 会话里的踩坑、修复、思考方式和工作流沉淀为可被后续 agent 读取的结构化知识。

如果不是这台机器，请把示例中的 `/Users/Zhuanz1/Desktop/knowledge-miner` 和 `/Users/Zhuanz1/Desktop/AI-Knowledge-Base/knowledge-base.json` 替换为你自己的项目路径和知识库路径。

## 当前能力

- 读取 Claude Code 项目会话：默认目录 `~/.claude/projects`
- 读取 Hermes 会话：默认目录 `~/.hermes/sessions`
- 输出到本地 JSON 知识库
- 兼容 `AI-Knowledge-Base` 的外层分类：`bug修复`、`新功能`、`最佳实践`、`行业动态`
- 写入时保留未知顶层字段、自定义分类和已有条目的自定义字段
- 在 `agent_knowledge` 中保存更适合 agent 读取的内部结构
- dry-run 会显示解析诊断，包括坏行、坏消息、文件错误和时间过滤数量
- 按消息时间过滤近期内容，避免老会话中的新消息被整段跳过
- 写入前自动备份已有知识库文件
- 默认预览不写入，真实写入必须显式确认
- 配置加载会校验数据源、分析粒度、内容优先级、布尔环境变量和输出路径
- 提供 MCP Server：`mine_knowledge`、`get_knowledge`、`get_stats`

Cursor、Windsurf、飞书云文档输出和定时任务是后续扩展方向，目前不是已完成能力。

## 本地开发安装

在项目目录安装：

```bash
cd /Users/Zhuanz1/Desktop/knowledge-miner
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

本机当前可直接使用：

```bash
/Users/Zhuanz1/Desktop/knowledge-miner/.venv/bin/knowledge-miner --help
/Users/Zhuanz1/Desktop/knowledge-miner/.venv/bin/knowledge-miner doctor
/Users/Zhuanz1/Desktop/knowledge-miner/.venv/bin/knowledge-miner doctor --mcp-smoke
/Users/Zhuanz1/Desktop/knowledge-miner/.venv/bin/knowledge-miner doctor --acceptance
```

## CLI 使用

默认只预览，不写入：

```bash
/Users/Zhuanz1/Desktop/knowledge-miner/.venv/bin/knowledge-miner mine --source claude --days 7
```

确认写入：

```bash
/Users/Zhuanz1/Desktop/knowledge-miner/.venv/bin/knowledge-miner mine --source claude --days 7 --yes
```

显式 dry-run：

```bash
/Users/Zhuanz1/Desktop/knowledge-miner/.venv/bin/knowledge-miner mine --source claude --days 7 --dry-run
```

读取知识库：

```bash
/Users/Zhuanz1/Desktop/knowledge-miner/.venv/bin/knowledge-miner read --section pitfalls
/Users/Zhuanz1/Desktop/knowledge-miner/.venv/bin/knowledge-miner read --format json
```

查看统计：

```bash
/Users/Zhuanz1/Desktop/knowledge-miner/.venv/bin/knowledge-miner stats
```

检查本地环境：

```bash
/Users/Zhuanz1/Desktop/knowledge-miner/.venv/bin/knowledge-miner doctor
/Users/Zhuanz1/Desktop/knowledge-miner/.venv/bin/knowledge-miner doctor --mcp-smoke
/Users/Zhuanz1/Desktop/knowledge-miner/.venv/bin/knowledge-miner doctor --acceptance
```

`doctor --acceptance` 会用临时 Hermes 会话和临时知识库路径跑完整 stdio MCP 流程：列工具、默认预览不写入、`confirm_write=true` 后写入、再读取统计。它不会修改真实的 `/Users/Zhuanz1/Desktop/AI-Knowledge-Base/knowledge-base.json`。

## MCP Server 接入

优先直接生成本机 MCP 配置片段：

```bash
/Users/Zhuanz1/Desktop/knowledge-miner/.venv/bin/knowledge-miner config --mcp-json
```

本机建议用 venv 里的绝对路径，避免 Claude/Codex 启动时找不到命令：

```json
{
  "mcpServers": {
    "knowledge-miner": {
      "command": "/Users/Zhuanz1/Desktop/knowledge-miner/.venv/bin/knowledge-miner",
      "args": ["mcp-server"],
      "env": {
        "KM_DATA_SOURCES": "claude,hermes",
        "KM_OUTPUT_PATH": "/Users/Zhuanz1/Desktop/AI-Knowledge-Base/knowledge-base.json"
      }
    }
  }
}
```

通用模板：

```json
{
  "mcpServers": {
    "knowledge-miner": {
      "command": "/ABSOLUTE/PATH/TO/knowledge-miner/.venv/bin/knowledge-miner",
      "args": ["mcp-server"],
      "env": {
        "KM_DATA_SOURCES": "claude,hermes",
        "KM_OUTPUT_PATH": "/ABSOLUTE/PATH/TO/knowledge-base.json"
      }
    }
  }
}
```

如果已经全局安装，也可以使用：

```json
{
  "mcpServers": {
    "knowledge-miner": {
      "command": "knowledge-miner",
      "args": ["mcp-server"]
    }
  }
}
```

## MCP 工具

| 工具 | 功能 | 关键参数 |
| --- | --- | --- |
| `mine_knowledge` | 从会话中提取知识并预览或写入知识库 | `days`, `source`, `dry_run`, `confirm_write` |
| `get_knowledge` | 读取已沉淀的知识 | `section` |
| `get_stats` | 查看知识库统计 | 无 |

`mine_knowledge` 默认不写入。真实写入必须传：

```json
{
  "source": "claude",
  "days": 7,
  "confirm_write": true
}
```

只预览：

```json
{
  "source": "claude",
  "days": 7,
  "dry_run": true
}
```

## 配置文件

配置文件路径：

```text
~/.knowledge-miner/config.json
```

MCP 配置中的 `KM_*` 环境变量会覆盖这个配置文件，适合在不同 agent 中指定不同数据源或输出路径。

配置加载会拒绝未知字段和非法值，例如未知数据源、空 `data-sources`、非法 `analysis-granularity`、非法 `content-priority`、布尔环境变量拼写错误，或 `output-path` 指向目录。

生成配置：

```bash
/Users/Zhuanz1/Desktop/knowledge-miner/.venv/bin/knowledge-miner config --init
```

示例：

```json
{
  "data-sources": ["claude", "hermes"],
  "claude-projects-dir": "~/.claude/projects",
  "hermes-sessions-dir": "~/.hermes/sessions",
  "output-path": "/Users/Zhuanz1/Desktop/AI-Knowledge-Base/knowledge-base.json",
  "feishu-enabled": false,
  "analysis-granularity": "global",
  "content-priority": ["pitfalls", "thinking_patterns", "workflows", "communication_style"],
  "cron-enabled": false,
  "cron-schedule": "0 23 * * *"
}
```

## 隐私与安全

knowledge-miner 会读取本机 AI agent 会话目录，例如 `~/.claude/projects` 和 `~/.hermes/sessions`。这些会话可能包含 API key、客户信息、文件路径、错误日志或业务细节。

默认安全行为：

- CLI `mine` 默认只预览，不写入；真实写入必须加 `--yes`
- MCP `mine_knowledge` 默认只预览，不写入；真实写入必须传 `confirm_write: true`
- 接入前可运行 `knowledge-miner doctor --mcp-smoke` 验证 stdio MCP 握手和工具列表
- 接入前可运行 `knowledge-miner doctor --acceptance` 用临时数据验证 MCP 端到端写入链路
- 写入已有知识库前会先生成 `.bak` 备份文件
- 写入会做保守合并，尽量保留用户自定义字段和分类
- 如果现有知识库 JSON 损坏，会先生成 `.corrupt.bak`，然后拒绝覆盖
- MCP 参数会做运行时校验，字符串 `"false"` 不会被当成确认写入

建议流程：

1. 先运行 `knowledge-miner doctor`
2. 再运行 `knowledge-miner doctor --mcp-smoke` 和 `knowledge-miner doctor --acceptance`
3. 先运行 `knowledge-miner mine --source claude --days 7` 看 dry-run 预览
4. 确认预览内容没有敏感信息后，再用 `--yes` 或 MCP `confirm_write: true` 写入
5. 如需公开分享知识库，请先人工检查并脱敏

## 环境变量

| 变量 | 说明 | 默认值 |
| --- | --- | --- |
| `KM_DATA_SOURCES` | 数据源，逗号分隔 | `claude,hermes` |
| `KM_CLAUDE_DIR` | Claude Code 项目目录 | `~/.claude/projects` |
| `KM_HERMES_DIR` | Hermes 会话目录 | `~/.hermes/sessions` |
| `KM_OUTPUT_PATH` | 知识库输出路径 | 优先使用 `~/Desktop/AI-Knowledge-Base/knowledge-base.json` |
| `KM_FEISHU_ENABLED` | 是否启用飞书配置字段 | `false` |
| `KM_GRANULARITY` | 分析粒度配置字段 | `global` |
| `KM_PRIORITY` | 内容优先级，逗号分隔 | `pitfalls,thinking_patterns,workflows,communication_style` |
| `KM_CRON_ENABLED` | 是否启用定时配置字段 | `false` |
| `KM_CRON_SCHEDULE` | 定时配置字段 | `0 23 * * *` |

## 输出结构

写入 `/Users/Zhuanz1/Desktop/AI-Knowledge-Base/knowledge-base.json` 时会保留外层知识库结构：

```json
{
  "version": "2.0",
  "categories": {
    "bug修复": [],
    "新功能": [],
    "最佳实践": [],
    "行业动态": []
  },
  "agent_knowledge": {
    "metadata": {},
    "pitfalls": {"items": []},
    "thinking_patterns": {"items": []},
    "workflows": {"items": []},
    "communication_style": {}
  }
}
```

`get_knowledge` 会优先返回 `agent_knowledge` 视图，便于 agent 直接读取。

## 验收命令

```bash
cd /Users/Zhuanz1/Desktop/knowledge-miner
.venv/bin/python -m pytest -q
.venv/bin/ruff check src tests
.venv/bin/knowledge-miner doctor
.venv/bin/knowledge-miner doctor --mcp-smoke
.venv/bin/knowledge-miner mine --source claude --days 7
```

最后一条命令未加 `--yes` 时应只输出预览，并且不修改真实知识库文件。
