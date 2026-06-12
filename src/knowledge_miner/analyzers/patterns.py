"""模式检测模块"""

import re
from collections import Counter
from typing import Any

from knowledge_miner.models import Message

# 错误关键词模式
ERROR_PATTERNS = [
    r"error[:\s]+(.+?)(?:\n|$)",
    r"报错[：:\s]+(.+?)(?:\n|$)",
    r"failed[:\s]+(.+?)(?:\n|$)",
    r"失败[：:\s]+(.+?)(?:\n|$)",
    r"exception[:\s]+(.+?)(?:\n|$)",
    r"异常[：:\s]+(.+?)(?:\n|$)",
    r"traceback\s+\(most recent call last\):",
    r"exit code[:\s]+([1-9]\d*)",
    r"runtimewarning[:\s]+(.+?)(?:\n|$)",
    r"permission denied[:\s]*(.+?)(?:\n|$)",
    r"no such file or directory[:\s]*(.+?)(?:\n|$)",
    r"command not found[:\s]*(.+?)(?:\n|$)",
    r"HTTP\s+(\d{3})\s*[:\-]?\s*(.+?)(?:\n|$)",
    r"不支持[：:\s]+(.+?)(?:\n|$)",
    r"不支持.+?model[:\s=]+[\"']?([^\"'\s]+)[\"']?",
]

# 修复关键词模式
FIX_PATTERNS = [
    r"修复[：:\s]+(.+?)(?:\n|$)",
    r"解决[：:\s]+(.+?)(?:\n|$)",
    (r"应该[：:\s]+(.+?)(?:\n|$)", "should"),
    (r"需要[：:\s]+(.+?)(?:\n|$)", "need"),
    (r"检查[：:\s]+(.+?)(?:\n|$)", "check"),
    (r"确认[：:\s]+(.+?)(?:\n|$)", "confirm"),
]

FAILURE_PATTERNS = [
    r"exit code[:\s]+[1-9]\d*",
    r"process exited with code\s+[1-9]\d*",
    r"\bfailed\b",
    r"traceback\s+\(most recent call last\):",
    r"runtimewarning[:\s]+",
    r"permission denied",
    r"no such file or directory",
    r"command not found",
]

SUCCESS_PATTERNS = [
    r"exit code[:\s]+0",
    r"process exited with code\s+0",
    r"\bpassed\b",
    r"\ball checks passed\b",
    r"\bsuccess(?:ful|fully)?\b",
    r"成功",
    r"通过",
]


def extract_errors(messages: list[Message]) -> list[dict[str, Any]]:
    """从消息中提取错误信息"""
    errors: list[dict[str, Any]] = []

    for msg in messages:
        if msg.role not in ("user", "assistant"):
            continue

        content = msg.content
        for pattern in ERROR_PATTERNS:
            if isinstance(pattern, tuple):
                regex, category = pattern
            else:
                regex = pattern
                category = "error"

            matches = re.finditer(regex, content, re.IGNORECASE | re.MULTILINE)
            for match in matches:
                error_text = match.group(0).strip()
                if len(error_text) < 10:  # 过滤太短的匹配
                    continue

                # 获取上下文（前后消息）
                context = _get_message_context(messages, msg, window=2)

                errors.append({
                    "text": error_text,
                    "category": category,
                    "timestamp": msg.timestamp,
                    "session_id": msg.session_id,
                    "context": context,
                })

    return errors


def extract_fixes(messages: list[Message]) -> list[dict[str, Any]]:
    """从消息中提取修复方案"""
    fixes: list[dict[str, Any]] = []

    for msg in messages:
        if msg.role not in ("user", "assistant"):
            continue

        content = msg.content
        for pattern in FIX_PATTERNS:
            if isinstance(pattern, tuple):
                regex, category = pattern
            else:
                regex = pattern
                category = "fix"

            matches = re.finditer(regex, content, re.IGNORECASE | re.MULTILINE)
            for match in matches:
                fix_text = match.group(0).strip()
                if len(fix_text) < 10:
                    continue

                fixes.append({
                    "text": fix_text,
                    "category": category,
                    "timestamp": msg.timestamp,
                    "session_id": msg.session_id,
                })

    return fixes


def extract_user_questions(messages: list[Message]) -> list[dict[str, Any]]:
    """提取用户问题模式"""
    questions: list[dict[str, Any]] = []

    question_patterns = [
        r"(.+?)[？?](?:\n|$)",
        r"如何[：:\s]+(.+?)(?:\n|$)",
        r"怎么[：:\s]+(.+?)(?:\n|$)",
        r"为什么[：:\s]+(.+?)(?:\n|$)",
        r"能不能[：:\s]+(.+?)(?:\n|$)",
        r"有没有[：:\s]+(.+?)(?:\n|$)",
    ]

    for msg in messages:
        if msg.role != "user":
            continue

        content = msg.content
        for pattern in question_patterns:
            matches = re.finditer(pattern, content)
            for match in matches:
                question = match.group(0).strip()
                if len(question) < 10 or len(question) > 500:
                    continue

                questions.append({
                    "text": question,
                    "timestamp": msg.timestamp,
                    "session_id": msg.session_id,
                })

    return questions


def extract_tool_usage(messages: list[Message]) -> dict[str, int]:
    """统计工具使用频率"""
    tool_patterns = {
        "git": (
            r"\bgit\s+"
            r"(?:status|diff|add|commit|push|pull|clone|branch|checkout|merge|rebase|log)\b"
        ),
        "npm": r"\bnpm\s+(?:install|run|test|build|start|publish|update)\b",
        "docker": r"\bdocker\s+(?:build|run|ps|images|pull|push|exec|logs)\b",
        "curl": r"\bcurl\s+",
        "python": r"\bpython[3]?\s+",
        "node": r"\bnode\s+",
        "pip": r"\bpip\s+(?:install|list|freeze)\b",
        "grep": r"\bgrep\s+",
        "sed": r"\bsed\s+",
        "find": r"\bfind\s+",
        "cat": r"\bcat\s+",
        "ls": r"\bls\b",
    }

    usage: Counter[str] = Counter()

    for msg in messages:
        for tool_use in msg.metadata.get("tool_uses", []):
            name = tool_use.get("name")
            if name:
                usage[name] += 1
            summary = tool_use.get("summary", "")
            for tool, pattern in tool_patterns.items():
                matches = re.findall(pattern, summary, re.IGNORECASE)
                usage[tool] += len(matches)

        content = msg.content
        for tool, pattern in tool_patterns.items():
            matches = re.findall(pattern, content, re.IGNORECASE)
            usage[tool] += len(matches)

    return dict(usage)


def extract_tool_failures(
    messages: list[Message],
    lookahead: int = 8,
) -> list[dict[str, Any]]:
    """Extract failed tool runs and nearby successful verification signals."""
    failures: list[dict[str, Any]] = []
    by_session = _group_by_session(messages)

    for session_messages in by_session.values():
        tool_uses = _tool_uses_by_id(session_messages)

        for index, msg in enumerate(session_messages):
            for result in msg.metadata.get("tool_results", []):
                content = result.get("content", "")
                if not _looks_like_failure(content, result.get("is_error", False)):
                    continue

                tool_use = tool_uses.get(result.get("tool_use_id", ""), {})
                verification = _find_successful_verification(
                    session_messages[index + 1 : index + 1 + lookahead],
                    tool_uses,
                )
                follow_up_actions = _find_follow_up_actions(
                    session_messages[index + 1 : index + 1 + lookahead],
                    limit=3,
                )
                failures.append(
                    {
                        "tool": tool_use.get("name", "unknown"),
                        "command": _tool_command(tool_use),
                        "error": content[:500],
                        "timestamp": msg.timestamp,
                        "session_id": msg.session_id,
                        "tool_use_id": result.get("tool_use_id", ""),
                        "follow_up_actions": follow_up_actions,
                        "verification": verification,
                        "context": _get_message_context(session_messages, msg, window=2),
                    }
                )

    return failures


def _get_message_context(
    messages: list[Message],
    target: Message,
    window: int = 2,
) -> list[dict[str, str]]:
    """获取消息的上下文"""
    context: list[dict[str, str]] = []

    # 找到目标消息的索引
    for i, msg in enumerate(messages):
        if msg.timestamp == target.timestamp and msg.session_id == target.session_id:
            # 获取前后消息
            start = max(0, i - window)
            end = min(len(messages), i + window + 1)

            for j in range(start, end):
                if j != i:
                    context.append({
                        "role": messages[j].role,
                        "content": messages[j].content[:200],  # 截断
                    })
            break

    return context


def _group_by_session(messages: list[Message]) -> dict[str, list[Message]]:
    grouped: dict[str, list[Message]] = {}
    for msg in messages:
        grouped.setdefault(msg.session_id, []).append(msg)
    return grouped


def _tool_uses_by_id(messages: list[Message]) -> dict[str, dict[str, Any]]:
    tool_uses: dict[str, dict[str, Any]] = {}
    for msg in messages:
        for tool_use in msg.metadata.get("tool_uses", []):
            tool_id = tool_use.get("id")
            if tool_id:
                tool_uses[tool_id] = tool_use
    return tool_uses


def _looks_like_failure(content: str, is_error: bool) -> bool:
    if is_error:
        return True
    return any(re.search(pattern, content, re.IGNORECASE) for pattern in FAILURE_PATTERNS)


def _looks_like_success(content: str) -> bool:
    return any(re.search(pattern, content, re.IGNORECASE) for pattern in SUCCESS_PATTERNS)


def _find_successful_verification(
    messages: list[Message],
    tool_uses: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    for msg in messages:
        for result in msg.metadata.get("tool_results", []):
            content = result.get("content", "")
            if not _looks_like_success(content):
                continue

            tool_use = tool_uses.get(result.get("tool_use_id", ""), {})
            return {
                "tool": tool_use.get("name", "unknown"),
                "command": _tool_command(tool_use),
                "output": content[:300],
            }
    return None


def _find_follow_up_actions(
    messages: list[Message],
    limit: int = 3,
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for msg in messages:
        for tool_use in msg.metadata.get("tool_uses", []):
            action = {
                "tool": tool_use.get("name", "unknown"),
                "command": _tool_command(tool_use),
            }
            if action["command"]:
                actions.append(action)
            if len(actions) >= limit:
                return actions
    return actions


def _tool_command(tool_use: dict[str, Any]) -> str:
    tool_input = tool_use.get("input", {})
    if not isinstance(tool_input, dict):
        return tool_use.get("summary", "")
    return (
        tool_input.get("command")
        or tool_input.get("file_path")
        or tool_input.get("path")
        or tool_use.get("summary", "")
    )
