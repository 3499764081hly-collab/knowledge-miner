from datetime import datetime

from knowledge_miner.analyzers.insights import InsightExtractor
from knowledge_miner.models import Message


def test_insight_extractor_adds_tool_failure_pitfalls() -> None:
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
    ]

    kb = InsightExtractor().extract_knowledge(
        messages=messages,
        sources=["claude"],
        date_range=(messages[0].timestamp, messages[-1].timestamp),
    )

    item = kb.pitfalls["items"][0]
    assert item["source"] == "tool_failure_chain"
    assert item["category"] == "tool_failure:Bash"
    assert item["command"] == "pytest -q"
    assert item["fingerprint"].startswith("fp_")
