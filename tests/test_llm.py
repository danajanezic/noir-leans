import json
import pytest
from noir.llm.mock import MockLLMBackend


def test_mock_llm_returns_configured_response():
    llm = MockLLMBackend(responses=["Hello, detective."])
    result = llm.query("You are a noir character.", [], "Hi")
    assert result == "Hello, detective."


def test_mock_llm_cycles_responses():
    llm = MockLLMBackend(responses=["First", "Second"])
    assert llm.query("sys", [], "a") == "First"
    assert llm.query("sys", [], "b") == "Second"
    assert llm.query("sys", [], "c") == "First"


def test_query_structured_parses_json():
    payload = {"victim": "Gerald Fitch", "cause": "spontaneous accordion"}
    llm = MockLLMBackend(responses=[json.dumps(payload)])
    result = llm.query_structured("sys", [], "generate case")
    assert result["victim"] == "Gerald Fitch"


def test_query_structured_retries_on_bad_json(capsys):
    good_payload = json.dumps({"key": "value"})
    llm = MockLLMBackend(responses=["not json", good_payload])
    result = llm.query_structured("sys", [], "generate")
    assert result["key"] == "value"


def test_query_structured_exits_on_double_failure(capsys):
    from noir.llm.base import FatalLLMError
    llm = MockLLMBackend(responses=["bad", "also bad"])
    with pytest.raises(FatalLLMError):
        llm.query_structured("sys", [], "generate")


def test_history_is_passed_to_query():
    llm = MockLLMBackend(responses=["ok"])
    history = [{"role": "user", "content": "prev"}, {"role": "assistant", "content": "resp"}]
    llm.query("sys", history, "new input")
    assert llm.last_history == history
