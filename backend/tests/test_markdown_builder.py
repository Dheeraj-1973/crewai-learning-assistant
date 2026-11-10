"""Tests for markdown_builder.py."""

from datetime import datetime, timezone

from app.services.markdown_builder import build_learning_notes, make_download_filename


def test_learning_notes_contain_every_section_in_order():
    notes = build_learning_notes(
        topic="Docker",
        teaching_plan="### Teaching Plan\n1. Containers",
        explanation="### What is Docker?\nDocker packages apps.",
        qa_pairs=[{"question": f"Question {n}?", "answer": f"Answer {n}."} for n in range(1, 4)],
        summary_points=[f"Point {n}" for n in range(1, 6)],
        generated_at=datetime(2026, 11, 10, 8, 30, tzinfo=timezone.utc),
    )
    assert notes.startswith("# Docker: Learning Notes")
    assert "10 Nov 2026, 08:30 UTC" in notes
    positions = [
        notes.index("## 1. Learning Plan"),
        notes.index("## 2. Topic Explanation"),
        notes.index("## 3. Questions and Answers"),
        notes.index("## 4. Five-Point Summary"),
    ]
    assert positions == sorted(positions)
    assert "### Q2. Question 2?\n\nAnswer 2." in notes
    assert "5. Point 5" in notes


def test_download_filename_is_safe():
    assert make_download_filename("Python Decorators!") == "python-decorators-learning-notes.md"
    assert make_download_filename("C++ / C#") == "c-c-learning-notes.md"
    assert make_download_filename("日本語") == "topic-learning-notes.md"
    assert make_download_filename('evil"; rm -rf /') == "evil-rm-rf-learning-notes.md"
