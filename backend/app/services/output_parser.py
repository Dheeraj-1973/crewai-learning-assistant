"""
Turn the raw text written by each agent into clean, validated data.

LLMs do not always follow formatting instructions perfectly. This module is
the safety net between "whatever the model wrote" and "what we save and show".

Rules followed here:

* Cleaning is deterministic (strip wrappers, markers, extra whitespace).
* We NEVER invent content. If an agent's output cannot be validated -
  for example the summary has 4 bullet points instead of 5 - we raise
  `OutputValidationError` and the generation is marked as failed with a
  clear message, instead of showing made-up or padded results.
* Small, harmless problems (e.g. the explanation looks cut off) are reported
  as warnings that the user can see, not hidden.

Everything here is plain Python with no CrewAI import, so it is easy to test.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

EXPLANATION_END_MARKER = "END_OF_EXPLANATION"
NOT_COVERED_MESSAGE = "The explanation does not cover this."

EXPECTED_QUESTIONS = 3
EXPECTED_SUMMARY_POINTS = 5


class OutputValidationError(ValueError):
    """Raised when an agent's output does not meet the required format."""


@dataclass
class CoordinatorOutput:
    teaching_plan: str
    questions: list[str]


@dataclass
class ExplanationOutput:
    text: str
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

_FENCE_WRAPPER = re.compile(r"^\s*```(?:markdown|md)?\s*\n(.*?)\n\s*```\s*$", re.DOTALL | re.IGNORECASE)


def strip_wrapping_code_fence(text: str) -> str:
    """Remove a ```markdown ... ``` fence that wraps the ENTIRE output."""
    match = _FENCE_WRAPPER.match(text)
    return match.group(1) if match else text


def _strip_inline_markup(text: str) -> str:
    """Remove bold/italic markers around a short line such as **Q1:**."""
    return re.sub(r"(\*\*|__)(.*?)\1", r"\2", text).strip()


def normalize_heading_levels(markdown: str, min_level: int = 3) -> str:
    """Shift headings so the biggest one is `min_level` (### by default).

    The final notes use # for the title and ## for the main sections, so
    the agents' own headings must be ### or smaller to keep a clean outline.
    Lines inside ``` code blocks are left untouched.
    """
    lines = markdown.split("\n")
    in_code = False
    levels: list[int] = []
    for line in lines:
        if line.lstrip().startswith("```"):
            in_code = not in_code
            continue
        match = re.match(r"^(#{1,6})\s", line)
        if match and not in_code:
            levels.append(len(match.group(1)))
    if not levels or min(levels) >= min_level:
        return markdown

    shift = min_level - min(levels)
    result = []
    in_code = False
    for line in lines:
        if line.lstrip().startswith("```"):
            in_code = not in_code
            result.append(line)
            continue
        match = re.match(r"^(#{1,6})(\s.*)$", line)
        if match and not in_code:
            new_level = min(6, len(match.group(1)) + shift)
            result.append("#" * new_level + match.group(2))
        else:
            result.append(line)
    return "\n".join(result)


def _require_text(raw: str | None, agent_name: str) -> str:
    if raw is None or not str(raw).strip():
        raise OutputValidationError(f"The {agent_name} returned an empty response.")
    return strip_wrapping_code_fence(str(raw).strip()).strip()


# ---------------------------------------------------------------------------
# Agent 1 - Learning Coordinator
# ---------------------------------------------------------------------------

_QUESTION_LINE = re.compile(
    r"^\s*(?:[-*]\s*)?(?:\*\*|__)?\s*Q(?:uestion)?\s*([1-9])\s*(?:\*\*|__)?\s*[:.)\-]\s*(?:\*\*|__)?\s*(.+?)\s*$",
    re.IGNORECASE,
)
_QUESTIONS_HEADING = re.compile(r"^\s*#{1,6}\s*(?:\d+\.\s*)?(?:\w+\s+)?questions\b.*$", re.IGNORECASE | re.MULTILINE)


def parse_coordinator_output(raw: str | None) -> CoordinatorOutput:
    """Split the Coordinator's output into (teaching plan, exactly 3 questions)."""
    text = _require_text(raw, "Learning Coordinator")

    questions: dict[int, str] = {}
    for line in text.splitlines():
        match = _QUESTION_LINE.match(line)
        if match:
            number = int(match.group(1))
            question = _strip_inline_markup(match.group(2))
            if number not in questions and question:
                questions[number] = question

    ordered = [questions[n] for n in sorted(questions)]
    if len(ordered) != EXPECTED_QUESTIONS:
        raise OutputValidationError(
            f"The Learning Coordinator produced {len(ordered)} questions instead of exactly "
            f"{EXPECTED_QUESTIONS}."
        )
    if len({q.lower() for q in ordered}) != EXPECTED_QUESTIONS:
        raise OutputValidationError("The Learning Coordinator repeated the same question.")

    # The teaching plan is everything before the questions heading (or before Q1).
    heading = _QUESTIONS_HEADING.search(text)
    if heading:
        plan = text[: heading.start()]
    else:
        first_q = next(i for i, line in enumerate(text.splitlines()) if _QUESTION_LINE.match(line))
        plan = "\n".join(text.splitlines()[:first_q])
    plan = normalize_heading_levels(plan.strip())
    if not plan:
        raise OutputValidationError("The Learning Coordinator did not produce a teaching plan.")

    return CoordinatorOutput(teaching_plan=plan, questions=ordered)


# ---------------------------------------------------------------------------
# Agent 2 - Content Teacher
# ---------------------------------------------------------------------------

# Headings that belong to OTHER agents. If the teacher adds such a section
# anyway, we cut it off so the final notes do not repeat content.
_FOREIGN_SECTION = re.compile(
    r"^\s*#{1,6}\s*(?:\d+\.\s*)?(?:practice\s+)?(?:q\s*&\s*a|questions(?:\s+and\s+answers)?|quiz|"
    r"summary|key\s+takeaways|recap|faq)\b.*$",
    re.IGNORECASE | re.MULTILINE,
)
_SENTENCE_END = re.compile(r"""[.!?:)"'`*\]]\s*$""")
MIN_EXPLANATION_CHARS = 400


def parse_explanation(raw: str | None) -> ExplanationOutput:
    """Clean the Content Teacher's explanation and check it is complete."""
    text = _require_text(raw, "Content Teacher")
    warnings: list[str] = []

    # 1. Completeness marker. The teacher is told to finish with this marker.
    #    If it is missing, the model most likely stopped early (truncation).
    if EXPLANATION_END_MARKER in text:
        text = text.split(EXPLANATION_END_MARKER, 1)[0].rstrip()
    else:
        warnings.append(
            "The explanation may be incomplete: the Content Teacher did not write its "
            "end-of-explanation marker, which usually means the response was cut short."
        )

    # 2. Remove sections that belong to the Q&A or Summary agents.
    foreign = _FOREIGN_SECTION.search(text)
    if foreign and foreign.start() > MIN_EXPLANATION_CHARS:
        text = text[: foreign.start()].rstrip()
        warnings.append(
            "A questions/summary section written by the Content Teacher was removed, "
            "because those parts are handled by the dedicated agents."
        )

    text = normalize_heading_levels(text.strip())

    if len(text) < MIN_EXPLANATION_CHARS:
        raise OutputValidationError(
            "The Content Teacher's explanation was too short to be useful "
            f"({len(text)} characters)."
        )

    # 3. A last sanity check on the final characters.
    last_line = text.rstrip().splitlines()[-1].strip()
    if not last_line.startswith("```") and not _SENTENCE_END.search(last_line):
        warnings.append("The explanation's last sentence looks unfinished.")

    return ExplanationOutput(text=text, warnings=warnings)


# ---------------------------------------------------------------------------
# Agent 3 - Grounded Q&A Specialist
# ---------------------------------------------------------------------------

_QA_MARKER = re.compile(
    r"^\s*(?:[-*]\s*)?(?:\*\*|__)?\s*(Q|A)(?:uestion|nswer)?\s*([1-9])\s*(?:\*\*|__)?\s*[:.)\-]\s*(?:\*\*|__)?\s*",
    re.IGNORECASE,
)


def parse_qa_output(raw: str | None, expected_questions: list[str]) -> list[dict[str, str]]:
    """Return exactly three {"question", "answer"} pairs from the Q&A agent.

    The question text always comes from the Coordinator (the source of truth),
    so a model that slightly rewords a question cannot change it.
    """
    text = _require_text(raw, "Q&A Specialist")

    answers: dict[int, list[str]] = {}
    current: int | None = None
    for line in text.splitlines():
        marker = _QA_MARKER.match(line)
        if marker:
            kind, number = marker.group(1).upper(), int(marker.group(2))
            rest = line[marker.end():]
            if kind == "Q":
                current = None  # question lines are not part of any answer
                continue
            current = number
            answers.setdefault(number, [])
            if rest.strip():
                answers[number].append(rest.strip())
        elif current is not None:
            answers[current].append(line.rstrip())

    pairs = []
    for index, question in enumerate(expected_questions, start=1):
        answer = "\n".join(answers.get(index, [])).strip()
        if not answer:
            raise OutputValidationError(f"The Q&A Specialist did not answer question {index}.")
        pairs.append({"question": question, "answer": answer})

    if len(pairs) != EXPECTED_QUESTIONS:
        raise OutputValidationError(
            f"Expected {EXPECTED_QUESTIONS} question-answer pairs but got {len(pairs)}."
        )
    return pairs


# ---------------------------------------------------------------------------
# Agent 4 - Summary Writer
# ---------------------------------------------------------------------------

_BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+(.+?)\s*$")


def parse_summary_output(raw: str | None) -> list[str]:
    """Return exactly five summary points, or raise OutputValidationError."""
    text = _require_text(raw, "Summary Writer")
    points = []
    for line in text.splitlines():
        match = _BULLET.match(line)
        if match:
            point = match.group(1).strip()
            if point:
                points.append(point)

    if len(points) != EXPECTED_SUMMARY_POINTS:
        raise OutputValidationError(
            f"The Summary Writer produced {len(points)} bullet points instead of exactly "
            f"{EXPECTED_SUMMARY_POINTS}."
        )
    return points
