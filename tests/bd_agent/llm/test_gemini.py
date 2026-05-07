"""tests/bd_agent/llm/test_gemini.py — Tests for GeminiProvider.

Strict TDD: these tests are written BEFORE the implementation (RED phase).
All tests mock google-genai at the SDK boundary — no real API calls are made.
"""
from __future__ import annotations

import os
import time
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

# Skip entire module if google-genai is not installed (SUGGESTION-1)
pytest.importorskip("google.genai")

from bd_agent.llm.provider import LLMMessage, LLMResponse, LLMToolCall, LLMProvider


# ---------------------------------------------------------------------------
# Helpers to build fake SDK responses
# ---------------------------------------------------------------------------

def _make_sdk_response(
    text: str | None = None,
    function_calls: list[dict] | None = None,
    finish_reason: str = "STOP",
    prompt_tokens: int = 10,
    candidates_tokens: int = 5,
) -> MagicMock:
    """Build a fake google.genai GenerateContentResponse."""
    response = MagicMock()

    # usage_metadata
    usage = MagicMock()
    usage.prompt_token_count = prompt_tokens
    usage.candidates_token_count = candidates_tokens
    usage.total_token_count = prompt_tokens + candidates_tokens
    response.usage_metadata = usage

    # candidates[0]
    candidate = MagicMock()
    candidate.finish_reason = finish_reason
    response.candidates = [candidate]

    # text property
    if text is not None:
        response.text = text
    else:
        # Accessing .text when there are tool calls raises (or returns None)
        response.text = None

    # function_calls
    if function_calls:
        fc_mocks = []
        for fc in function_calls:
            fmc = MagicMock()
            fmc.name = fc["name"]
            fmc.args = fc["args"]
            fmc.id = fc.get("id", f"call_{fc['name']}")
            fc_mocks.append(fmc)
        response.function_calls = fc_mocks
    else:
        response.function_calls = None

    return response


# ---------------------------------------------------------------------------
# T-041: GeminiProvider tests
# ---------------------------------------------------------------------------

class TestGeminiProviderImport:
    def test_module_importable(self) -> None:
        from bd_agent.llm.gemini import GeminiProvider  # noqa: F401

    def test_satisfies_llm_provider_protocol(self) -> None:
        from bd_agent.llm.gemini import GeminiProvider

        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}):
            provider = GeminiProvider()
        assert isinstance(provider, LLMProvider)

    def test_reads_api_key_from_env(self) -> None:
        from bd_agent.llm.gemini import GeminiProvider

        with patch.dict(os.environ, {"GEMINI_API_KEY": "my-secret-key"}):
            with patch("bd_agent.llm.gemini.genai.Client") as mock_client_cls:
                GeminiProvider()
                mock_client_cls.assert_called_once_with(api_key="my-secret-key")

    def test_raises_if_api_key_missing(self) -> None:
        from bd_agent.llm.gemini import GeminiProvider

        env = {k: v for k, v in os.environ.items() if k != "GEMINI_API_KEY"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(EnvironmentError, match="GEMINI_API_KEY"):
                GeminiProvider()


class TestGeminiProviderGenerate:
    """Test GeminiProvider.generate() method."""

    @pytest.fixture
    def provider(self):
        from bd_agent.llm.gemini import GeminiProvider

        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}):
            with patch("bd_agent.llm.gemini.genai.Client"):
                p = GeminiProvider()
                # Expose the mock client for test inspection
                return p

    def test_text_only_response(self, provider) -> None:
        """When Gemini returns text with no function calls, response.text is set."""
        fake_resp = _make_sdk_response(text="Las ventas de hoy son $1.500", finish_reason="STOP")

        with patch.object(provider._client.models, "generate_content", return_value=fake_resp):
            result = provider.generate(
                messages=[LLMMessage(role="user", content="dame ventas")],
                tools=None,
                system_prompt="Sos el Asistente de Badie",
            )

        assert isinstance(result, LLMResponse)
        assert result.text == "Las ventas de hoy son $1.500"
        assert result.tool_calls == []

    def test_tool_call_response(self, provider) -> None:
        """When Gemini returns function_calls, result.tool_calls is populated."""
        fake_resp = _make_sdk_response(
            text=None,
            function_calls=[
                {"name": "get_ventas_cliente", "args": {"id_cliente": 42, "periodo": "2026-04"}, "id": "call_1"}
            ],
            finish_reason="STOP",
        )

        with patch.object(provider._client.models, "generate_content", return_value=fake_resp):
            result = provider.generate(
                messages=[LLMMessage(role="user", content="ventas del cliente 42")],
                tools=[{"name": "get_ventas_cliente", "description": "...", "parameters": {}}],
                system_prompt="Sos el Asistente de Badie",
            )

        assert result.text is None
        assert len(result.tool_calls) == 1
        tc = result.tool_calls[0]
        assert tc.name == "get_ventas_cliente"
        assert tc.arguments == {"id_cliente": 42, "periodo": "2026-04"}
        assert tc.id == "call_1"

    def test_usage_populated(self, provider) -> None:
        """Usage metadata is mapped to prompt_tokens/completion_tokens/total_tokens."""
        fake_resp = _make_sdk_response(
            text="ok", finish_reason="STOP", prompt_tokens=100, candidates_tokens=50
        )

        with patch.object(provider._client.models, "generate_content", return_value=fake_resp):
            result = provider.generate(
                messages=[LLMMessage(role="user", content="test")],
                tools=None,
                system_prompt="sys",
            )

        assert result.usage is not None
        assert result.usage["prompt_tokens"] == 100
        assert result.usage["completion_tokens"] == 50
        assert result.usage["total_tokens"] == 150

    def test_usage_none_when_metadata_missing(self, provider) -> None:
        """If usage_metadata is None, result.usage is None (no crash)."""
        fake_resp = _make_sdk_response(text="ok", finish_reason="STOP")
        fake_resp.usage_metadata = None

        with patch.object(provider._client.models, "generate_content", return_value=fake_resp):
            result = provider.generate(
                messages=[LLMMessage(role="user", content="test")],
                tools=None,
                system_prompt="sys",
            )

        assert result.usage is None

    def test_system_prompt_sent_as_system_instruction(self, provider) -> None:
        """system_prompt is sent via GenerateContentConfig.system_instruction."""
        fake_resp = _make_sdk_response(text="ok", finish_reason="STOP")

        with patch("bd_agent.llm.gemini.types.GenerateContentConfig") as mock_config_cls:
            mock_config_cls.return_value = MagicMock()
            with patch.object(provider._client.models, "generate_content", return_value=fake_resp):
                provider.generate(
                    messages=[LLMMessage(role="user", content="test")],
                    tools=None,
                    system_prompt="Sos el Asistente de Badie",
                )

        call_kwargs = mock_config_cls.call_args
        assert call_kwargs is not None
        # system_instruction should be the system prompt string
        kwargs = call_kwargs.kwargs if hasattr(call_kwargs, "kwargs") else call_kwargs[1]
        assert kwargs.get("system_instruction") == "Sos el Asistente de Badie"

    def test_tools_sent_when_provided(self, provider) -> None:
        """When tools are provided, they are passed as types.Tool to the config."""
        fake_resp = _make_sdk_response(text="ok", finish_reason="STOP")
        tools = [{"name": "test_tool", "description": "A test tool", "parameters": {"type": "object", "properties": {}}}]

        with patch("bd_agent.llm.gemini.types.GenerateContentConfig") as mock_config_cls:
            mock_config_cls.return_value = MagicMock()
            with patch("bd_agent.llm.gemini.types.Tool") as mock_tool_cls:
                mock_tool_cls.return_value = MagicMock()
                with patch.object(provider._client.models, "generate_content", return_value=fake_resp):
                    provider.generate(
                        messages=[LLMMessage(role="user", content="test")],
                        tools=tools,
                        system_prompt="sys",
                    )

            mock_tool_cls.assert_called_once()

    def test_no_tools_sent_when_none(self, provider) -> None:
        """When tools=None, no Tool is created and config has no tools."""
        fake_resp = _make_sdk_response(text="ok", finish_reason="STOP")

        with patch("bd_agent.llm.gemini.types.GenerateContentConfig") as mock_config_cls:
            mock_config_cls.return_value = MagicMock()
            with patch("bd_agent.llm.gemini.types.Tool") as mock_tool_cls:
                with patch.object(provider._client.models, "generate_content", return_value=fake_resp):
                    provider.generate(
                        messages=[LLMMessage(role="user", content="test")],
                        tools=None,
                        system_prompt="sys",
                    )

            mock_tool_cls.assert_not_called()

    def test_messages_converted_to_contents(self, provider) -> None:
        """Messages are converted to Gemini Content format before the call."""
        fake_resp = _make_sdk_response(text="ok", finish_reason="STOP")

        with patch.object(provider._client.models, "generate_content", return_value=fake_resp) as mock_gen:
            provider.generate(
                messages=[
                    LLMMessage(role="user", content="primer mensaje"),
                    LLMMessage(role="assistant", content="respuesta"),
                    LLMMessage(role="user", content="segunda pregunta"),
                ],
                tools=None,
                system_prompt="sys",
            )

        call_kwargs = mock_gen.call_args
        # contents should be passed as a keyword arg or positional
        assert call_kwargs is not None
        # Find the 'contents' argument
        if call_kwargs.kwargs.get("contents") is not None:
            contents = call_kwargs.kwargs["contents"]
        else:
            contents = call_kwargs.args[1] if len(call_kwargs.args) > 1 else None

        assert contents is not None
        assert len(contents) == 3


class TestGeminiProviderBackoff:
    """Test retry/backoff behavior on 429 and 5xx errors."""

    @pytest.fixture
    def provider(self):
        from bd_agent.llm.gemini import GeminiProvider

        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}):
            with patch("bd_agent.llm.gemini.genai.Client"):
                return GeminiProvider()

    def _make_api_error(self, code: int) -> Exception:
        """Create a real APIError subclass with the given status code."""
        from google.genai import errors

        class FakeAPIError(errors.APIError):
            def __init__(self, status_code: int) -> None:
                self.code = status_code
                self.status = str(status_code)
                self.message = f"HTTP {status_code}"
                self.details = {}
                Exception.__init__(self, f"{status_code} Error")

        return FakeAPIError(code)

    def test_retries_on_429(self, provider) -> None:
        """On 429, the provider retries up to 3 times with backoff, then raises."""
        from google.genai import errors

        api_error = self._make_api_error(429)
        api_error.__class__ = errors.APIError

        with patch.object(
            provider._client.models,
            "generate_content",
            side_effect=api_error,
        ):
            with patch("bd_agent.llm.gemini.time.sleep") as mock_sleep:
                with pytest.raises(Exception):
                    provider.generate(
                        messages=[LLMMessage(role="user", content="test")],
                        tools=None,
                        system_prompt="sys",
                    )

            # Should have slept between retries: 3 retries = 3 sleeps (or 2 between them)
            assert mock_sleep.call_count >= 1

    def test_retries_on_503(self, provider) -> None:
        """On 503, same backoff logic as 429."""
        from google.genai import errors

        api_error = self._make_api_error(503)
        api_error.__class__ = errors.APIError

        with patch.object(
            provider._client.models,
            "generate_content",
            side_effect=api_error,
        ):
            with patch("bd_agent.llm.gemini.time.sleep") as mock_sleep:
                with pytest.raises(Exception):
                    provider.generate(
                        messages=[LLMMessage(role="user", content="test")],
                        tools=None,
                        system_prompt="sys",
                    )

            assert mock_sleep.call_count >= 1

    def test_max_3_retries_on_transient_error(self, provider) -> None:
        """Provider retries exactly 3 times (4 total calls) before giving up."""
        from google.genai import errors

        api_error = self._make_api_error(429)
        api_error.__class__ = errors.APIError

        with patch.object(
            provider._client.models,
            "generate_content",
            side_effect=api_error,
        ) as mock_gen:
            with patch("bd_agent.llm.gemini.time.sleep"):
                with pytest.raises(Exception):
                    provider.generate(
                        messages=[LLMMessage(role="user", content="test")],
                        tools=None,
                        system_prompt="sys",
                    )

        # 1 initial + 3 retries = 4 total calls
        assert mock_gen.call_count == 4

    def test_succeeds_on_second_try_after_429(self, provider) -> None:
        """If the first call raises 429 but the second succeeds, result is returned."""
        from google.genai import errors

        api_error = self._make_api_error(429)
        api_error.__class__ = errors.APIError
        fake_resp = _make_sdk_response(text="ok after retry", finish_reason="STOP")

        with patch.object(
            provider._client.models,
            "generate_content",
            side_effect=[api_error, fake_resp],
        ):
            with patch("bd_agent.llm.gemini.time.sleep"):
                result = provider.generate(
                    messages=[LLMMessage(role="user", content="test")],
                    tools=None,
                    system_prompt="sys",
                )

        assert result.text == "ok after retry"

    def test_no_retry_on_400(self, provider) -> None:
        """400 (Bad Request) is not a transient error — no retry, raises immediately."""
        from google.genai import errors

        api_error = self._make_api_error(400)
        api_error.__class__ = errors.APIError

        with patch.object(
            provider._client.models,
            "generate_content",
            side_effect=api_error,
        ) as mock_gen:
            with patch("bd_agent.llm.gemini.time.sleep") as mock_sleep:
                with pytest.raises(Exception):
                    provider.generate(
                        messages=[LLMMessage(role="user", content="test")],
                        tools=None,
                        system_prompt="sys",
                    )

        # Only 1 call — no retries for 400
        assert mock_gen.call_count == 1
        mock_sleep.assert_not_called()

    def test_no_retry_on_401_auth_error(self, provider) -> None:
        """401 (auth error) is not retried."""
        from google.genai import errors

        api_error = self._make_api_error(401)
        api_error.__class__ = errors.APIError

        with patch.object(
            provider._client.models,
            "generate_content",
            side_effect=api_error,
        ) as mock_gen:
            with patch("bd_agent.llm.gemini.time.sleep") as mock_sleep:
                with pytest.raises(Exception):
                    provider.generate(
                        messages=[LLMMessage(role="user", content="test")],
                        tools=None,
                        system_prompt="sys",
                    )

        assert mock_gen.call_count == 1
        mock_sleep.assert_not_called()

    def test_backoff_delays_increase(self, provider) -> None:
        """Sleep delays increase between retries (exponential backoff)."""
        from google.genai import errors

        api_error = self._make_api_error(429)
        api_error.__class__ = errors.APIError
        sleep_calls: list[float] = []

        def capture_sleep(seconds: float) -> None:
            sleep_calls.append(seconds)

        with patch.object(
            provider._client.models,
            "generate_content",
            side_effect=api_error,
        ):
            with patch("bd_agent.llm.gemini.time.sleep", side_effect=capture_sleep):
                with pytest.raises(Exception):
                    provider.generate(
                        messages=[LLMMessage(role="user", content="test")],
                        tools=None,
                        system_prompt="sys",
                    )

        assert len(sleep_calls) >= 2
        # Each delay should be >= the previous one (increasing backoff)
        for i in range(1, len(sleep_calls)):
            assert sleep_calls[i] >= sleep_calls[i - 1]


class TestGeminiProviderMessageConversion:
    """Test that the message conversion function handles all role types."""

    @pytest.fixture
    def provider(self):
        from bd_agent.llm.gemini import GeminiProvider

        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}):
            with patch("bd_agent.llm.gemini.genai.Client"):
                return GeminiProvider()

    def test_mixed_tool_response_and_text(self, provider) -> None:
        """Multiple function calls in one response are all parsed."""
        fake_resp = _make_sdk_response(
            text=None,
            function_calls=[
                {"name": "get_ventas_cliente", "args": {"id_cliente": 1}, "id": "c1"},
                {"name": "get_clientes_sucursal", "args": {"id_sucursal": 5}, "id": "c2"},
            ],
            finish_reason="STOP",
        )

        with patch.object(provider._client.models, "generate_content", return_value=fake_resp):
            result = provider.generate(
                messages=[LLMMessage(role="user", content="dame info")],
                tools=[
                    {"name": "get_ventas_cliente", "description": "...", "parameters": {}},
                    {"name": "get_clientes_sucursal", "description": "...", "parameters": {}},
                ],
                system_prompt="sys",
            )

        assert len(result.tool_calls) == 2
        names = [tc.name for tc in result.tool_calls]
        assert "get_ventas_cliente" in names
        assert "get_clientes_sucursal" in names

    def test_uses_gemini_flash_lite_model(self, provider) -> None:
        """GeminiProvider uses 'gemini-2.0-flash-lite' by default."""
        fake_resp = _make_sdk_response(text="ok", finish_reason="STOP")

        with patch.object(
            provider._client.models, "generate_content", return_value=fake_resp
        ) as mock_gen:
            provider.generate(
                messages=[LLMMessage(role="user", content="test")],
                tools=None,
                system_prompt="sys",
            )

        call_kwargs = mock_gen.call_args
        # model should be the first positional arg or 'model' kwarg
        assert call_kwargs is not None
        model_used = (
            call_kwargs.kwargs.get("model")
            or (call_kwargs.args[0] if call_kwargs.args else None)
        )
        assert model_used == "gemini-2.0-flash-lite"

    def test_no_src_imports(self) -> None:
        """gemini.py must have zero imports from src.*"""
        import ast
        import pathlib

        src = pathlib.Path("/home/nahuel/projects/work/Informes Badie/bd_agent/llm/gemini.py").read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.ImportFrom) and node.module:
                    assert not node.module.startswith("src."), (
                        f"bd_agent/llm/gemini.py imports from src.*: {node.module}"
                    )
