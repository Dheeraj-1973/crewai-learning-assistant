"""
Tests for crewai_service.py that do NOT run CrewAI or call Groq.

They check the agent definitions, the prompt templates and the safety
helpers. `run_learning_crew` itself is only tested for the "no API key"
path, which returns before CrewAI is even imported.
"""

import re
from dataclasses import replace

import pytest

from app.core.config import LLM_MODEL, get_settings
from app.services import crewai_service as svc


def test_four_distinct_agents_with_the_original_roles():
    roles = [spec["role"] for spec in svc.AGENT_SPECS.values()]
    assert roles == [
        "Learning Coordinator",
        "Beginner-Friendly Content Teacher",
        "Grounded Question Answering Specialist",
        "Beginner-Friendly Summary Writer",
    ]


def test_model_is_the_required_groq_model():
    assert LLM_MODEL == "groq/openai/gpt-oss-20b"
    assert get_settings().llm_model == LLM_MODEL


@pytest.mark.parametrize(
    "template",
    [
        svc.COORDINATOR_TASK, svc.COORDINATOR_OUTPUT, svc.TEACHER_TASK, svc.TEACHER_OUTPUT,
        svc.QA_TASK, svc.QA_OUTPUT, svc.SUMMARY_TASK, svc.SUMMARY_OUTPUT,
    ],
)
def test_prompts_only_use_the_topic_placeholder(template):
    # CrewAI fills {placeholders}; any other {...} would break kickoff().
    assert set(re.findall(r"\{(\w*)\}", template)) <= {"topic"}


def test_prompts_enforce_the_division_of_work():
    assert "exactly three questions" in svc.COORDINATOR_TASK
    assert "Do NOT include any questions" in svc.TEACHER_TASK
    assert "END_OF_EXPLANATION" in svc.TEACHER_TASK
    assert "Use ONLY information found in the Content Teacher's explanation" in svc.QA_TASK
    assert "exactly five bullet points" in svc.SUMMARY_TASK


def test_missing_api_key_stops_before_any_llm_call():
    no_key = replace(get_settings(), groq_api_key="")
    with pytest.raises(svc.LLMNotConfiguredError):
        svc.run_learning_crew("FastAPI", settings=no_key)


def test_error_messages_never_contain_api_keys():
    settings = replace(get_settings(), groq_api_key="gsk_SECRET1234567890")
    error = RuntimeError("bad request with key gsk_SECRET1234567890 and gsk_OTHERKEY12345678")
    message = svc.safe_error_message(error, settings)
    assert "SECRET" not in message and "OTHERKEY" not in message


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("RateLimitError: 429 Too Many Requests", "rate limit"),
        ("AuthenticationError: Invalid API Key", "rejected the API key"),
        ("Request timed out", "too long"),
    ],
)
def test_common_errors_get_friendly_messages(text, expected):
    assert expected in svc.safe_error_message(RuntimeError(text), get_settings())
