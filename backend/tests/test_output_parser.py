"""
Tests for output_parser.py - the code that checks every agent's output.
These are plain Python tests: no web server, database or LLM involved.
"""

import pytest

from app.services.output_parser import (
    NOT_COVERED_MESSAGE,
    OutputValidationError,
    normalize_heading_levels,
    parse_coordinator_output,
    parse_explanation,
    parse_qa_output,
    parse_summary_output,
    strip_wrapping_code_fence,
)
from tests import fakes

QUESTIONS = ["What is X?", "How does X work?", "When should I use X?"]


# --- Coordinator --------------------------------------------------------------

def test_coordinator_output_is_split_into_plan_and_questions():
    result = parse_coordinator_output(fakes.COORDINATOR_TEXT)
    assert result.questions == [
        "What is FastAPI?",
        "How does FastAPI validate incoming data?",
        "When would a beginner choose FastAPI?",
    ]
    assert result.teaching_plan.startswith("### Teaching Plan")
    assert "Q1" not in result.teaching_plan
    assert "### Questions" not in result.teaching_plan


def test_coordinator_accepts_bold_and_question_word_variants():
    text = (
        "## Plan\n1. Step\n\n## Questions\n"
        "**Q1:** First?\n- **Question 2.** Second?\nQ3) Third?\n"
    )
    result = parse_coordinator_output(text)
    assert result.questions == ["First?", "Second?", "Third?"]
    assert result.teaching_plan == "### Plan\n1. Step"  # heading shifted to ###


@pytest.mark.parametrize(
    "text",
    [
        "### Plan\n1. Step\n### Questions\nQ1: One?\nQ2: Two?",                     # only two
        "### Plan\n1. Step\n### Questions\nQ1: One?\nQ2: Two?\nQ3: Three?\nQ4: Four?",  # four
        "### Plan\n1. Step\n### Questions\nQ1: Same?\nQ2: same?\nQ3: Other?",        # duplicate
        "### Questions\nQ1: One?\nQ2: Two?\nQ3: Three?",                              # no plan
        "",
        None,
    ],
)
def test_coordinator_invalid_outputs_raise(text):
    with pytest.raises(OutputValidationError):
        parse_coordinator_output(text)


# --- Content Teacher -------------------------------------------------------------

def test_explanation_marker_is_removed_and_no_warnings():
    result = parse_explanation(fakes.EXPLANATION_TEXT)
    assert "END_OF_EXPLANATION" not in result.text
    assert result.warnings == []


def test_missing_marker_produces_truncation_warning():
    truncated = fakes.EXPLANATION_TEXT.replace("END_OF_EXPLANATION", "").rstrip()[:-40]
    result = parse_explanation(truncated)
    assert any("incomplete" in warning for warning in result.warnings)
    assert any("unfinished" in warning for warning in result.warnings)


def test_qa_section_written_by_teacher_is_removed():
    text = fakes.EXPLANATION_TEXT.replace(
        "END_OF_EXPLANATION", "### Questions and Answers\nQ1: x\nA1: y\nEND_OF_EXPLANATION"
    )
    result = parse_explanation(text)
    assert "Questions and Answers" not in result.text
    assert any("removed" in warning for warning in result.warnings)


def test_explanation_headings_are_normalized():
    text = "# Big\n" + "word " * 100 + ".\n## Medium\nMore text.\nEND_OF_EXPLANATION"
    result = parse_explanation(text)
    assert result.text.startswith("### Big")
    assert "\n#### Medium" in result.text


def test_too_short_explanation_raises():
    with pytest.raises(OutputValidationError):
        parse_explanation("Too short.\nEND_OF_EXPLANATION")


def test_headings_inside_code_blocks_are_untouched():
    text = "## Title\n```bash\n# a shell comment\n```"
    assert normalize_heading_levels(text) == "### Title\n```bash\n# a shell comment\n```"


def test_wrapping_code_fence_is_removed():
    assert strip_wrapping_code_fence("```markdown\n### Hi\ntext\n```") == "### Hi\ntext"
    assert strip_wrapping_code_fence("text\n```py\nx=1\n```") == "text\n```py\nx=1\n```"


# --- Q&A Specialist -----------------------------------------------------------------

def test_qa_pairs_use_coordinator_questions():
    raw = "Q1: what is x\nA1: Answer one.\n\nQ2: ...\nA2: Answer two\nwith a second line.\n\nQ3: ...\nA3: " + NOT_COVERED_MESSAGE
    pairs = parse_qa_output(raw, QUESTIONS)
    assert [pair["question"] for pair in pairs] == QUESTIONS
    assert pairs[0]["answer"] == "Answer one."
    assert pairs[1]["answer"] == "Answer two\nwith a second line."
    assert pairs[2]["answer"] == NOT_COVERED_MESSAGE


def test_qa_accepts_bold_markers():
    raw = "**Q1:** x\n**A1:** One.\n**Q2:** y\n**A2:** Two.\n**Q3:** z\n**A3:** Three."
    assert [p["answer"] for p in parse_qa_output(raw, QUESTIONS)] == ["One.", "Two.", "Three."]


def test_missing_answer_raises():
    with pytest.raises(OutputValidationError, match="question 3"):
        parse_qa_output("Q1: a\nA1: one\nQ2: b\nA2: two\nQ3: c\n", QUESTIONS)


# --- Summary Writer -----------------------------------------------------------------

def test_summary_with_five_bullets():
    points = parse_summary_output(fakes.SUMMARY_TEXT)
    assert len(points) == 5
    assert points[0] == "FastAPI is a Python framework for building web APIs."


def test_summary_accepts_other_bullet_styles():
    raw = "* one\n• two\n1. three\n2) four\n- five"
    assert parse_summary_output(raw) == ["one", "two", "three", "four", "five"]


@pytest.mark.parametrize("count", [0, 4, 6])
def test_summary_with_wrong_number_of_bullets_raises(count):
    raw = "Intro line\n" + "\n".join(f"- point {i}" for i in range(count))
    with pytest.raises(OutputValidationError):
        parse_summary_output(raw)
