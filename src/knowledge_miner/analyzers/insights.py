"""洞察提取模块 - 核心分析引擎"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Any

from knowledge_miner.analyzers.patterns import (
    extract_errors,
    extract_fixes,
    extract_tool_failures,
    extract_tool_usage,
    extract_user_questions,
)
from knowledge_miner.config import get_config
from knowledge_miner.models import (
    KnowledgeBase,
    create_empty_knowledge_base,
)


class InsightExtractor:
    """知识洞察提取器"""

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}
        self._counter = 0

    def _next_id(self, prefix: str) -> str:
        """生成下一个 ID"""
        self._counter += 1
        return f"{prefix}_{self._counter:03d}"

    def extract_knowledge(
        self,
        messages: list[Any],
        sources: list[str],
        date_range: tuple[datetime, datetime],
    ) -> KnowledgeBase:
        """从消息中提取知识"""
        # 创建空知识库
        kb = create_empty_knowledge_base(
            sources=sources,
            date_range=date_range,
            total_sessions=len(set(m.session_id for m in messages)),
        )

        # 按优先级提取
        priority = get_config().content_priority

        if "pitfalls" in priority:
            kb.pitfalls = self._extract_pitfalls(messages)

        if "thinking_patterns" in priority:
            kb.thinking_patterns = self._extract_thinking_patterns(messages)

        if "workflows" in priority:
            kb.workflows = self._extract_workflows(messages)

        if "communication_style" in priority:
            kb.communication_style = self._extract_communication_style(messages)

        # 更新元数据
        kb.metadata["generated_at"] = datetime.now().isoformat()
        kb.metadata["total_messages"] = len(messages)

        return kb

    def _extract_pitfalls(self, messages: list[Any]) -> dict[str, Any]:
        """提取踩过的坑"""
        errors = extract_errors(messages)
        fixes = extract_fixes(messages)
        tool_failures = extract_tool_failures(messages)

        # 按类别聚类错误
        categories: dict[str, list[dict]] = {}
        for error in errors:
            cat = error["category"]
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(error)

        # 构建坑列表
        pitfalls: list[dict[str, Any]] = []

        for failure in tool_failures[:10]:
            last_seen = failure["timestamp"]
            if isinstance(last_seen, datetime):
                last_seen = last_seen.isoformat()
            verification = failure.get("verification")
            follow_up_actions = failure.get("follow_up_actions", [])
            verification_text = ""
            if verification:
                verification_text = (
                    f"；验证：{verification.get('command') or verification.get('output', '')}"
                )
            follow_up_text = _format_follow_up_actions(follow_up_actions)

            tool = failure.get("tool", "unknown")
            command = failure.get("command", "")
            error_text = failure.get("error", "")
            if verification:
                fix = f"查看后续修复动作{verification_text}"
            elif follow_up_text:
                fix = f"后续尝试：{follow_up_text}"
            else:
                fix = "待补充"

            pitfalls.append(
                {
                    "id": self._next_id("pitfall"),
                    "fingerprint": _fingerprint(
                        "tool_failure",
                        tool,
                        command,
                        _first_line(error_text),
                    ),
                    "category": f"tool_failure:{tool}",
                    "mistake": f"{command}\n{error_text}"[:300],
                    "fix": fix[:300],
                    "frequency": 1,
                    "context": "工具调用失败链路",
                    "examples": [failure.get("error", "")[:150]],
                    "last_seen": last_seen,
                    "tool": tool,
                    "command": command,
                    "follow_up_actions": follow_up_actions,
                    "verification": verification,
                    "source": "tool_failure_chain",
                }
            )

        for cat, error_list in categories.items():
            # 提取修复方案
            related_fixes = self._find_related_fixes(error_list, fixes)

            for error in error_list[:5]:  # 每类最多 5 个
                last_seen = error["timestamp"]
                if isinstance(last_seen, datetime):
                    last_seen = last_seen.isoformat()

                pitfall = {
                    "id": self._next_id("pitfall"),
                    "fingerprint": _fingerprint(
                        "regex_error",
                        cat,
                        _first_line(error["text"]),
                    ),
                    "category": cat,
                    "mistake": error["text"][:200],
                    "fix": related_fixes[0]["text"][:200] if related_fixes else "待补充",
                    "frequency": len(error_list),
                    "context": cat,
                    "examples": [error["text"][:100]],
                    "last_seen": last_seen,
                }
                pitfalls.append(pitfall)

        return {
            "priority": "A",
            "items": pitfalls,
        }

    def _extract_thinking_patterns(self, messages: list[Any]) -> dict[str, Any]:
        """提取思维方式"""
        questions = extract_user_questions(messages)
        tool_usage = extract_tool_usage(messages)

        patterns: list[dict[str, Any]] = []

        # 分析问题风格
        if questions:
            why_count = sum(
                1
                for q in questions
                if "为什么" in q["text"] or "why" in q["text"].lower()
            )
            how_count = sum(
                1
                for q in questions
                if "如何" in q["text"]
                or "怎么" in q["text"]
                or "how" in q["text"].lower()
            )

            if why_count > len(questions) * 0.3:
                patterns.append({
                    "id": self._next_id("pattern"),
                    "name": "原因探究型",
                    "description": "喜欢问'为什么'，注重理解底层原因",
                    "frequency": round(why_count / len(questions), 2),
                    "context": "问题分析",
                    "examples": [q["text"][:100] for q in questions if "为什么" in q["text"]][:3],
                })

            if how_count > len(questions) * 0.3:
                patterns.append({
                    "id": self._next_id("pattern"),
                    "name": "方法导向型",
                    "description": "喜欢问'如何'，注重解决方案",
                    "frequency": round(how_count / len(questions), 2),
                    "context": "问题解决",
                    "examples": [
                        q["text"][:100]
                        for q in questions
                        if "如何" in q["text"] or "怎么" in q["text"]
                    ][:3],
                })

        # 分析工具使用
        if tool_usage:
            sorted_tools = sorted(tool_usage.items(), key=lambda x: x[1], reverse=True)
            top_tools = sorted_tools[:3]
            total_usage = sum(tool_usage.values())

            for tool, count in top_tools:
                patterns.append({
                    "id": self._next_id("pattern"),
                    "name": f"常用工具: {tool}",
                    "description": f"频繁使用 {tool} 工具",
                    "frequency": round(count / total_usage, 2) if total_usage > 0 else 0,
                    "context": "工具使用",
                    "examples": [],
                })

        return {
            "priority": "B",
            "items": patterns,
        }

    def _extract_workflows(self, messages: list[Any]) -> dict[str, Any]:
        """提取工作流"""
        tool_usage = extract_tool_usage(messages)
        workflows: list[dict[str, Any]] = []

        # Git 工作流
        if tool_usage.get("git", 0) > 5:
            workflows.append({
                "id": self._next_id("workflow"),
                "name": "Git 工作流",
                "steps": ["git status", "git diff", "git add", "git commit", "git push"],
                "frequency": tool_usage["git"],
                "context": "版本控制",
            })

        # Debug 工作流（通过错误和修复检测）
        errors = extract_errors(messages)
        if len(errors) > 3:
            workflows.append({
                "id": self._next_id("workflow"),
                "name": "Debug 工作流",
                "steps": ["复现错误", "查看日志", "定位根因", "实施修复", "验证结果"],
                "frequency": len(errors),
                "context": "问题排查",
            })

        return {
            "priority": "C",
            "items": workflows,
        }

    def _extract_communication_style(self, messages: list[Any]) -> dict[str, Any]:
        """提取沟通风格"""
        user_messages = [m for m in messages if m.role == "user"]
        if not user_messages:
            return {
                "priority": "D",
                "formality": "unknown",
                "detail_level": "unknown",
                "prefers_examples": False,
                "language": "unknown",
                "response_preferences": {},
            }

        # 分析消息长度
        avg_length = sum(len(m.content) for m in user_messages) / len(user_messages)

        # 检测语言
        chinese_count = sum(
            1 for m in user_messages if any("一" <= c <= "鿿" for c in m.content)
        )
        language = "chinese_preferred" if chinese_count > len(user_messages) * 0.5 else "mixed"

        # 检测是否偏好示例
        example_keywords = ["示例", "例子", "比如", "例如", "example", "such as"]
        example_count = sum(
            1
            for m in user_messages
            if any(kw in m.content for kw in example_keywords)
        )
        prefers_examples = example_count > len(user_messages) * 0.2

        return {
            "priority": "D",
            "formality": "casual_technical",
            "detail_level": "moderate" if avg_length < 200 else "detailed",
            "prefers_examples": prefers_examples,
            "language": language,
            "response_preferences": {
                "concise_vs_detailed": "context_dependent",
                "code_vs_explanation": "both",
                "step_by_step": True,
            },
        }

    def _find_related_fixes(
        self, errors: list[dict], fixes: list[dict]
    ) -> list[dict]:
        """查找与错误相关的修复方案"""
        related: list[dict] = []

        for error in errors:
            error_time = error["timestamp"]
            for fix in fixes:
                fix_time = fix["timestamp"]
                # 修复时间在错误之后 10 分钟内
                if isinstance(error_time, datetime) and isinstance(fix_time, datetime):
                    if 0 <= (fix_time - error_time).total_seconds() <= 600:
                        related.append(fix)
                        break

        return related[:3]


def _format_follow_up_actions(actions: list[dict[str, Any]]) -> str:
    parts = []
    for action in actions:
        tool = action.get("tool", "unknown")
        command = action.get("command", "")
        if command:
            parts.append(f"{tool}: {command}")
    return "；".join(parts)


def _fingerprint(*parts: Any) -> str:
    normalized = "|".join(_normalize_for_fingerprint(part) for part in parts)
    digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:16]
    return f"fp_{digest}"


def _normalize_for_fingerprint(value: Any) -> str:
    text = str(value or "").lower()
    text = re.sub(r"/Users/[^\\s]+", "/users/<path>", text)
    text = re.sub(r"\b\d{4}-\d{2}-\d{2}[t\s]\d{2}:\d{2}:\d{2}(?:\.\d+)?\b", "<datetime>", text)
    text = re.sub(r"\b[0-9a-f]{8,}\b", "<hex>", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:240]


def _first_line(value: Any) -> str:
    return str(value or "").strip().splitlines()[0] if str(value or "").strip() else ""
