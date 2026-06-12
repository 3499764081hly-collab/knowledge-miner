from datetime import datetime

from knowledge_miner.analyzers.patterns import (
    extract_errors,
    extract_tool_failures,
    extract_tool_usage,
)
from knowledge_miner.models import Message


def test_extract_tool_usage_reads_metadata_and_command_summary() -> None:
    messages = [
        Message(
            role="assistant",
            content="[tool_use:Bash] command=git status",
            timestamp=datetime(2026, 6, 10),
            session_id="s1",
            source="claude",
            metadata={
                "tool_uses": [
                    {"name": "Bash", "summary": "command=git status"},
                    {"name": "Edit", "summary": "file_path=src/app.py"},
                ]
            },
        )
    ]

    usage = extract_tool_usage(messages)

    assert usage["Bash"] == 1
    assert usage["Edit"] == 1
    assert usage["git"] >= 1


def test_extract_errors_reads_tool_result_failures() -> None:
    messages = [
        Message(
            role="user",
            content="[tool_result:toolu_1] Exit code: 1\nFAILED tests/test_demo.py",
            timestamp=datetime(2026, 6, 10),
            session_id="s1",
            source="claude",
        )
    ]

    errors = extract_errors(messages)

    assert errors
    assert any("Exit code: 1" in error["text"] for error in errors)


def test_extract_tool_failures_links_command_and_verification() -> None:
    messages = [
        Message(
            role="assistant",
            content="[tool_use:Bash] command=pytest -q",
            timestamp=datetime(2026, 6, 10, 12, 0, 0),
            session_id="s1",
            source="claude",
            metadata={
                "tool_uses": [
                    {"id": "u1", "name": "Bash", "input": {"command": "pytest -q"}}
                ]
            },
        ),
        Message(
            role="user",
            content="[tool_result:u1] Exit code: 1\nFAILED tests/test_demo.py",
            timestamp=datetime(2026, 6, 10, 12, 0, 1),
            session_id="s1",
            source="claude",
            metadata={
                "tool_results": [
                    {
                        "tool_use_id": "u1",
                        "content": "Exit code: 1\nFAILED tests/test_demo.py",
                    }
                ]
            },
        ),
        Message(
            role="assistant",
            content="[tool_use:Bash] command=pytest -q",
            timestamp=datetime(2026, 6, 10, 12, 1, 0),
            session_id="s1",
            source="claude",
            metadata={
                "tool_uses": [
                    {"id": "u2", "name": "Bash", "input": {"command": "pytest -q"}}
                ]
            },
        ),
        Message(
            role="user",
            content="[tool_result:u2] Exit code: 0\n15 passed",
            timestamp=datetime(2026, 6, 10, 12, 1, 1),
            session_id="s1",
            source="claude",
            metadata={
                "tool_results": [
                    {"tool_use_id": "u2", "content": "Exit code: 0\n15 passed"}
                ]
            },
        ),
    ]

    failures = extract_tool_failures(messages)

    assert len(failures) == 1
    assert failures[0]["tool"] == "Bash"
    assert failures[0]["command"] == "pytest -q"
    assert failures[0]["verification"]["command"] == "pytest -q"


def test_extract_tool_failures_reads_process_exited_format_and_followups() -> None:
    messages = [
        Message(
            role="assistant",
            content="[tool_use:Bash] command=npm test",
            timestamp=datetime(2026, 6, 10, 12, 0, 0),
            session_id="s1",
            source="claude",
            metadata={
                "tool_uses": [
                    {"id": "u1", "name": "Bash", "input": {"command": "npm test"}}
                ]
            },
        ),
        Message(
            role="user",
            content="[tool_result:u1] Process exited with code 1\nAssertionError",
            timestamp=datetime(2026, 6, 10, 12, 0, 1),
            session_id="s1",
            source="claude",
            metadata={
                "tool_results": [
                    {
                        "tool_use_id": "u1",
                        "content": "Process exited with code 1\nAssertionError",
                    }
                ]
            },
        ),
        Message(
            role="assistant",
            content="[tool_use:Edit] file_path=src/app.js",
            timestamp=datetime(2026, 6, 10, 12, 1, 0),
            session_id="s1",
            source="claude",
            metadata={
                "tool_uses": [
                    {"id": "u2", "name": "Edit", "input": {"file_path": "src/app.js"}}
                ]
            },
        ),
        Message(
            role="assistant",
            content="[tool_use:Bash] command=npm test",
            timestamp=datetime(2026, 6, 10, 12, 2, 0),
            session_id="s1",
            source="claude",
            metadata={
                "tool_uses": [
                    {"id": "u3", "name": "Bash", "input": {"command": "npm test"}}
                ]
            },
        ),
        Message(
            role="user",
            content="[tool_result:u3] Process exited with code 0\nAll checks passed!",
            timestamp=datetime(2026, 6, 10, 12, 2, 1),
            session_id="s1",
            source="claude",
            metadata={
                "tool_results": [
                    {
                        "tool_use_id": "u3",
                        "content": "Process exited with code 0\nAll checks passed!",
                    }
                ]
            },
        ),
    ]

    failures = extract_tool_failures(messages)

    assert len(failures) == 1
    assert failures[0]["follow_up_actions"][0]["tool"] == "Edit"
    assert failures[0]["follow_up_actions"][0]["command"] == "src/app.js"
    assert failures[0]["verification"]["command"] == "npm test"
