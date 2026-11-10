"""
Combine the four agents' validated outputs into one Markdown document.

This is the file the user downloads ("Complete Learning Notes").
"""

from __future__ import annotations

import re
from datetime import datetime

from app.core.config import LLM_MODEL


def build_learning_notes(
    *,
    topic: str,
    teaching_plan: str,
    explanation: str,
    qa_pairs: list[dict[str, str]],
    summary_points: list[str],
    generated_at: datetime,
) -> str:
    """Return the complete learning notes as a Markdown string."""
    lines: list[str] = [
        f"# {topic}: Learning Notes",
        "",
        f"> Generated on {generated_at.strftime('%d %b %Y, %H:%M UTC')} by the CrewAI "
        f"Multi-Agent Learning Assistant (model: `{LLM_MODEL}`).",
        "> AI-generated content can contain mistakes. Check important details against "
        "official documentation.",
        "",
        "## 1. Learning Plan",
        "",
        teaching_plan.strip(),
        "",
        "## 2. Topic Explanation",
        "",
        explanation.strip(),
        "",
        "## 3. Questions and Answers",
        "",
    ]
    for number, pair in enumerate(qa_pairs, start=1):
        lines += [f"### Q{number}. {pair['question']}", "", pair["answer"].strip(), ""]

    lines += ["## 4. Five-Point Summary", ""]
    lines += [f"{number}. {point}" for number, point in enumerate(summary_points, start=1)]
    lines.append("")
    return "\n".join(lines)


def make_download_filename(topic: str) -> str:
    """'Python Decorators!' -> 'python-decorators-learning-notes.md'."""
    slug = re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")[:60].strip("-")
    return f"{slug or 'topic'}-learning-notes.md"
