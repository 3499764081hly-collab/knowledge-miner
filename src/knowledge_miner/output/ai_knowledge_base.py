"""AI-Knowledge-Base compatible storage helpers."""

from __future__ import annotations

import re
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

from knowledge_miner.models import KnowledgeBase

CATEGORY_KEYS = ["bug修复", "新功能", "最佳实践", "行业动态"]


def should_use_ai_knowledge_base_schema(
    output_path: Path,
    existing_data: dict[str, Any] | None = None,
) -> bool:
    """Return whether the target should preserve the AI-Knowledge-Base schema."""
    if existing_data and "categories" in existing_data:
        return True
    return (
        output_path.name == "knowledge-base.json"
        and output_path.parent.name == "AI-Knowledge-Base"
    )


def to_ai_knowledge_base_dict(
    knowledge_base: KnowledgeBase,
    existing_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Convert the internal agent knowledge model into the user's knowledge base file."""
    now = datetime.now().isoformat()
    existing = deepcopy(existing_data) if existing_data else {}
    result = deepcopy(existing)
    categories = _existing_categories(existing)

    agent_knowledge = knowledge_base.to_dict()
    categories["bug修复"] = _merge_items(
        categories["bug修复"],
        [_pitfall_to_category_item(item) for item in _items(agent_knowledge, "pitfalls")],
    )
    categories["最佳实践"] = _merge_items(
        categories["最佳实践"],
        [_workflow_to_category_item(item) for item in _items(agent_knowledge, "workflows")]
        + [
            _pattern_to_category_item(item)
            for item in _items(agent_knowledge, "thinking_patterns")
        ],
    )

    result.update(
        {
            "version": "2.0",
            "created": existing.get("created") or datetime.now().date().isoformat(),
            "updated_at": now,
            "qa_count": existing.get("qa_count", 0),
            "categories": categories,
            "agent_knowledge": agent_knowledge,
            "monthly_stats": existing.get("monthly_stats", {}),
        }
    )

    return result


def summarize_ai_knowledge_base_update(
    knowledge_base: KnowledgeBase,
    output_path: Path,
    existing_data: dict[str, Any] | None = None,
    sample_limit: int = 10,
) -> dict[str, Any]:
    """Summarize how a write would affect the target storage file."""
    agent_knowledge = knowledge_base.to_dict()
    existing = existing_data or {}

    if not should_use_ai_knowledge_base_schema(output_path, existing_data):
        return {
            "schema": "agent_knowledge",
            "would_add": None,
            "would_merge": None,
            "categories": {},
        }

    existing_categories = existing.get("categories", {})
    incoming_by_category = {
        "bug修复": [
            _pitfall_to_category_item(item)
            for item in _items(agent_knowledge, "pitfalls")
        ],
        "最佳实践": [
            _workflow_to_category_item(item)
            for item in _items(agent_knowledge, "workflows")
        ]
        + [
            _pattern_to_category_item(item)
            for item in _items(agent_knowledge, "thinking_patterns")
        ],
        "新功能": [],
        "行业动态": [],
    }

    categories: dict[str, dict[str, int]] = {}
    samples: list[dict[str, Any]] = []
    total_add = 0
    total_merge = 0
    for category in CATEGORY_KEYS:
        existing_keys = {
            _merge_key(item)
            for item in existing_categories.get(category, [])
            if isinstance(item, dict)
        }
        incoming = incoming_by_category.get(category, [])
        would_merge = sum(1 for item in incoming if _merge_key(item) in existing_keys)
        would_add = len(incoming) - would_merge
        category_samples = [
            _preview_item(
                category=category,
                item=item,
                operation="merge" if _merge_key(item) in existing_keys else "add",
            )
            for item in incoming[:sample_limit]
        ]
        categories[category] = {
            "incoming": len(incoming),
            "would_add": would_add,
            "would_merge": would_merge,
            "samples": category_samples,
        }
        samples.extend(category_samples)
        total_add += would_add
        total_merge += would_merge

    return {
        "schema": "ai_knowledge_base",
        "would_add": total_add,
        "would_merge": total_merge,
        "categories": categories,
        "samples": samples[:sample_limit],
        "preserved": _preserved_summary(existing),
    }


def extract_agent_view(data: dict[str, Any]) -> dict[str, Any]:
    """Return the internal agent knowledge view from either storage schema."""
    if "agent_knowledge" in data and isinstance(data["agent_knowledge"], dict):
        return data["agent_knowledge"]
    return data


def _empty_categories() -> dict[str, list[dict[str, Any]]]:
    return {key: [] for key in CATEGORY_KEYS}


def _existing_categories(existing: dict[str, Any]) -> dict[str, Any]:
    categories = existing.get("categories")
    if not isinstance(categories, dict):
        return _empty_categories()

    preserved = deepcopy(categories)
    for key in CATEGORY_KEYS:
        value = preserved.get(key)
        preserved[key] = value if isinstance(value, list) else []
    return preserved


def _preserved_summary(existing: dict[str, Any]) -> dict[str, list[str]]:
    categories = existing.get("categories")
    category_keys = set(categories) if isinstance(categories, dict) else set()
    known_top_level = {
        "version",
        "created",
        "updated_at",
        "qa_count",
        "categories",
        "agent_knowledge",
        "monthly_stats",
    }
    return {
        "unknown_top_level_fields": sorted(set(existing) - known_top_level),
        "unknown_categories": sorted(category_keys - set(CATEGORY_KEYS)),
    }


def _items(agent_knowledge: dict[str, Any], section: str) -> list[dict[str, Any]]:
    section_data = agent_knowledge.get(section, {})
    if not isinstance(section_data, dict):
        return []
    items = section_data.get("items", [])
    return items if isinstance(items, list) else []


def _pitfall_to_category_item(item: dict[str, Any]) -> dict[str, Any]:
    title, summary = _humanize_pitfall(item)
    return {
        "id": item.get("id"),
        "fingerprint": item.get("fingerprint"),
        "title": title,
        "summary": summary,
        "solution": item.get("fix", ""),
        "source_section": "pitfalls",
        "frequency": item.get("frequency", 0),
        "last_seen": item.get("last_seen"),
        "examples": item.get("examples", []),
        "tool": item.get("tool"),
        "command": item.get("command"),
        "follow_up_actions": item.get("follow_up_actions", []),
        "verification": item.get("verification"),
    }


def _workflow_to_category_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id"),
        "fingerprint": item.get("fingerprint"),
        "title": item.get("name") or "未命名工作流",
        "summary": " / ".join(item.get("steps", [])),
        "source_section": "workflows",
        "frequency": item.get("frequency", 0),
        "context": item.get("context", ""),
    }


def _pattern_to_category_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id"),
        "fingerprint": item.get("fingerprint"),
        "title": item.get("name") or "未命名模式",
        "summary": item.get("description", ""),
        "source_section": "thinking_patterns",
        "frequency": item.get("frequency", 0),
        "context": item.get("context", ""),
        "examples": item.get("examples", []),
    }


def _merge_items(
    existing_items: list[Any],
    new_items: list[dict[str, Any]],
) -> list[Any]:
    passthrough: list[Any] = []
    merged: dict[str, dict[str, Any]] = {}
    for item in existing_items:
        if isinstance(item, dict):
            merged[_merge_key(item)] = deepcopy(item)
        else:
            passthrough.append(deepcopy(item))
    for item in new_items:
        key = _merge_key(item)
        if key in merged:
            merged[key] = _merge_item(merged[key], item)
        else:
            merged[key] = item
    return passthrough + list(merged.values())


def _merge_key(item: dict[str, Any]) -> str:
    return str(
        item.get("fingerprint")
        or item.get("id")
        or item.get("title")
        or item.get("summary")
    )


def _merge_item(existing: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(existing)
    merged["id"] = existing.get("id") or new.get("id")
    merged["fingerprint"] = existing.get("fingerprint") or new.get("fingerprint")
    merged["title"] = new.get("title") or existing.get("title")
    merged["summary"] = new.get("summary") or existing.get("summary")
    merged["solution"] = new.get("solution") or existing.get("solution")
    merged["source_section"] = new.get("source_section") or existing.get("source_section")
    merged["frequency"] = int(existing.get("frequency") or 0) + int(new.get("frequency") or 0)
    merged["last_seen"] = _max_text(existing.get("last_seen"), new.get("last_seen"))
    merged["examples"] = _dedupe_list(existing.get("examples", []) + new.get("examples", []))[:5]

    for key in ("tool", "command", "follow_up_actions", "verification", "context"):
        if new.get(key):
            merged[key] = new[key]

    return merged


def _preview_item(category: str, item: dict[str, Any], operation: str) -> dict[str, Any]:
    return {
        "operation": operation,
        "category": category,
        "title": item.get("title", ""),
        "summary": _clip(item.get("summary", "")),
        "solution": _clip(item.get("solution", "")),
        "fingerprint": item.get("fingerprint"),
        "source_section": item.get("source_section"),
    }


def _dedupe_list(items: list[Any]) -> list[Any]:
    result: list[Any] = []
    seen: set[str] = set()
    for item in items:
        key = str(item)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _max_text(left: Any, right: Any) -> Any:
    if not left:
        return right
    if not right:
        return left
    return max(str(left), str(right))


def _clip(value: Any, max_chars: int = 180) -> str:
    text = str(value or "")
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def _humanize_pitfall(item: dict[str, Any]) -> tuple[str, str]:
    category = str(item.get("category") or "")
    command = str(item.get("command") or "")
    mistake = str(item.get("mistake") or "")
    error_line = _first_informative_line(mistake, fallback=category, skip=command)

    if item.get("source") == "tool_failure_chain" or category.startswith("tool_failure:"):
        title = _title_for_tool_failure(command=command, error_line=error_line, category=category)
        summary = _summary_for_tool_failure(command=command, error_line=error_line)
        return title, summary

    if category and category != "error":
        return category, _clip(error_line or mistake)
    return _title_from_error(error_line), _clip(error_line or mistake)


def _title_for_tool_failure(command: str, error_line: str, category: str) -> str:
    combined = f"{command}\n{error_line}".lower()
    file_hint = _extract_file_hint(error_line) or _extract_file_hint(command)

    if "tsc" in combined or "typescript" in combined or re.search(r"\bts\d{4}\b", combined):
        suffix = f"：{file_hint}" if file_hint else ""
        return f"TypeScript 类型检查失败{suffix}"
    if "pytest" in combined or "assertionerror" in combined:
        suffix = f"：{file_hint}" if file_hint else ""
        return f"pytest 测试失败{suffix}"
    if "npm" in combined and ("failed" in combined or "error" in combined):
        return "npm 脚本执行失败"
    if "curl" in combined or "http" in combined:
        return "HTTP 请求或服务探测失败"
    if "permission denied" in combined:
        return "权限不足导致工具调用失败"
    if "no such file or directory" in combined:
        return "路径不存在导致工具调用失败"
    if category == "tool_failure:Read":
        suffix = f"：{file_hint}" if file_hint else ""
        return f"读取文件失败{suffix}"
    if category == "tool_failure:Edit":
        suffix = f"：{file_hint}" if file_hint else ""
        return f"编辑文件失败{suffix}"
    if command:
        return f"命令执行失败：{_clip(command, 60)}"
    return category or "工具调用失败"


def _summary_for_tool_failure(command: str, error_line: str) -> str:
    if not command:
        return _clip(error_line)
    action = f"触发动作：{_clip(command, 90)}"
    error = f"关键错误：{_clip(error_line, 120)}" if error_line else "关键错误：未识别"
    return f"{action}；{error}"


def _title_from_error(error_line: str) -> str:
    lower = error_line.lower()
    if "http" in lower:
        return "HTTP/API 调用错误"
    if "permission denied" in lower:
        return "权限错误"
    if "no such file or directory" in lower:
        return "路径不存在错误"
    if "failed" in lower or "失败" in error_line:
        return "执行失败"
    return "错误经验"


def _first_informative_line(text: str, fallback: str = "", skip: str = "") -> str:
    normalized_skip = skip.strip()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("[tool_result:"):
            continue
        if normalized_skip and line == normalized_skip:
            continue
        if line.startswith(">"):
            continue
        return line
    return fallback


def _extract_file_hint(text: str) -> str:
    match = re.search(r"([\w./-]+\.(?:tsx|ts|jsx|js|py|json|md|cjs|mjs))", text)
    if not match:
        return ""
    return Path(match.group(1)).name
