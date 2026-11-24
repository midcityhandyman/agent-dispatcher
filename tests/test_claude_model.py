"""ClaudeModel against a fake client. No network and no anthropic package needed."""

from types import SimpleNamespace

import pytest

from agent_dispatcher import Dispatcher
from agent_dispatcher.errors import ModelError
from agent_dispatcher.models.base import Model, ModelRequest
from agent_dispatcher.models.claude import DEFAULT_MODEL, FALLBACK_BETA, ClaudeModel
from agent_dispatcher.models.mock import MockModel
from agent_dispatcher import prompts

REQUEST = ModelRequest(role="worker", system="system text", prompt="prompt text", max_tokens=1234)


def response(*texts, stop_reason="end_turn", **extra):
    blocks = [SimpleNamespace(type="thinking", thinking="")] + [SimpleNamespace(type="text", text=t) for t in texts]
    return SimpleNamespace(content=blocks, stop_reason=stop_reason, **extra)


class FakeClient:
    def __init__(self, reply=None, error=None):
        self.reply, self.error = reply, error
        self.calls, self.beta_calls = [], []
        self.messages = SimpleNamespace(create=self._create)
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._beta_create))

    def _create(self, **params):
        self.calls.append(params)
        if self.error:
            raise self.error
        return self.reply

    def _beta_create(self, **params):
        self.beta_calls.append(params)
        return self.reply


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ("AGENT_DISPATCHER_MODEL", "AGENT_DISPATCHER_EFFORT", "AGENT_DISPATCHER_FALLBACKS"):
        monkeypatch.delenv(name, raising=False)


def test_default_model_id_and_request_shape():
    client = FakeClient(response("hello ", "world"))
    model = ClaudeModel(client=client)
    assert model.model == DEFAULT_MODEL == "claude-sonnet-5-5"
    assert model.complete(REQUEST) == "hello world"
    assert client.calls == [
        {
            "model": "claude-sonnet-5-5",
            "max_tokens": 1234,
            "system": "system text",
            "messages": [{"role": "user", "content": "prompt text"}],
        }
    ]


def test_model_is_configurable_by_argument_and_environment(monkeypatch):
    monkeypatch.setenv("AGENT_DISPATCHER_MODEL", "claude-from-env")
    assert ClaudeModel(client=FakeClient()).model == "claude-from-env"
    assert ClaudeModel("claude-from-arg", client=FakeClient()).model == "claude-from-arg"


def test_effort_is_sent_inside_output_config_only_when_set(monkeypatch):
    monkeypatch.setenv("AGENT_DISPATCHER_EFFORT", "low")
    client = FakeClient(response("ok"))
    ClaudeModel(client=client).complete(REQUEST)
    assert client.calls[0]["output_config"] == {"effort": "low"}


def test_no_thinking_or_sampling_parameters_are_sent():
    client = FakeClient(response("ok"))
    ClaudeModel(client=client).complete(REQUEST)
    assert not {"thinking", "temperature", "top_p", "top_k"} & set(client.calls[0])


def test_fallbacks_opt_in_uses_the_beta_endpoint():
    client = FakeClient(response("ok"))
    ClaudeModel(client=client, fallbacks="default").complete(REQUEST)
    assert client.calls == []
    assert client.beta_calls[0]["betas"] == [FALLBACK_BETA]
    assert client.beta_calls[0]["fallbacks"] == "default"


def test_refusal_is_an_error_not_an_empty_answer():
    reply = response(stop_reason="refusal", stop_details=SimpleNamespace(category="cyber"))
    with pytest.raises(ModelError, match="refused.*cyber"):
        ClaudeModel(client=FakeClient(reply)).complete(REQUEST)


def test_truncated_reply_is_an_error():
    with pytest.raises(ModelError, match="max_tokens"):
        ClaudeModel(client=FakeClient(response('{"output": "half', stop_reason="max_tokens"))).complete(REQUEST)


def test_reply_without_text_is_an_error():
    with pytest.raises(ModelError, match="no text"):
        ClaudeModel(client=FakeClient(response())).complete(REQUEST)


def test_client_exceptions_become_model_errors():
    with pytest.raises(ModelError, match="boom"):
        ClaudeModel(client=FakeClient(error=RuntimeError("boom"))).complete(REQUEST)


def test_missing_credentials_are_named_plainly():
    error = TypeError('"Could not resolve authentication method. Expected one of api_key, auth_token"')
    with pytest.raises(ModelError, match="no API credentials found; set ANTHROPIC_API_KEY"):
        ClaudeModel(client=FakeClient(error=error)).complete(REQUEST)


def test_both_implementations_satisfy_the_interface():
    assert isinstance(ClaudeModel(client=FakeClient()), Model)
    assert isinstance(MockModel(), Model)


def test_dispatcher_runs_end_to_end_on_claude_model_with_a_scripted_client():
    """The Claude adapter in the loop, with the mock supplying the reply text."""
    brain = MockModel()
    roles = {prompts.LEAD_SYSTEM: "lead", prompts.WORKER_SYSTEM: "worker", prompts.VERIFIER_SYSTEM: "verifier"}

    class Relay(FakeClient):
        def _create(self, **params):
            self.calls.append(params)
            role = roles[params["system"]]
            text = brain.complete(ModelRequest(role, params["system"], params["messages"][0]["content"]))
            return response("```json\n" + text + "\n```")

    client = Relay()
    report = Dispatcher(ClaudeModel(client=client)).run("draft the agenda, then list the action items")
    assert report.all_accepted
    assert len(client.calls) == 5  # one lead, two workers, two verifiers
