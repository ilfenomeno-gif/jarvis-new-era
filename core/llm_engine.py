from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import yaml

from core import llm_budget, llm_events
from core.deepseek_adapter import DeepSeekAdapter
from core.gemini_adapter import GeminiAdapter
from core.llm_context import get_context, with_context
from core.noop_adapter import NoopAdapter
from core.ollama_adapter import OllamaAdapter
from core.openai_compat_adapter import OpenAICompatAdapter

_POLICY_PATH = Path(__file__).resolve().parents[1] / "config" / "llm_policy.yaml"
_LOGGER = logging.getLogger(__name__)
_LEGACY_WARNED: set[str] = set()
_LOCK = threading.RLock()
_TRANSIENT_WORDS = (
    "timeout", "timed out", "connection", "temporarily", "429", "500",
    "502", "503", "504", "unavailable", "rate limit",
)


class LLMError(RuntimeError):
    error_code = "llm_error"


class LLMAuthError(LLMError):
    error_code = "auth_missing"


class LLMConfigError(LLMError):
    error_code = "invalid_config"


class LLMBudgetExceeded(LLMError):
    error_code = "budget_exceeded"


def _load_policy() -> dict:
    try:
        with _POLICY_PATH.open(encoding="utf-8") as policy_file:
            policy = yaml.safe_load(policy_file)
    except (OSError, yaml.YAMLError) as exc:
        raise LLMConfigError(f"Could not load LLM policy: {exc}") from exc
    if not isinstance(policy, dict) or not isinstance(policy.get("roles"), dict):
        raise LLMConfigError("LLM policy must define a roles mapping.")
    return policy


def _key_names(provider: str, provider_policy: dict) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    configured_env = provider_policy.get("api_key_env")
    if provider == "gemini":
        return (
            ("GOOGLE_API_KEY", "GEMINI_API_KEY"),
            ("gemini_api_key", "google_api_key"),
            ("gemini_api_key", "google_api_key"),
        )
    if provider == "deepseek":
        return (
            (configured_env or "DEEPSEEK_API_KEY",),
            ("deepseek_api_key",),
            ("deepseek_api_key",),
        )
    if provider in ("openai", "openai_compat"):
        return (("OPENAI_API_KEY",), ("openai_api_key",), ("openai_api_key",))
    return ((), (), ())


def _read_legacy_keys() -> dict:
    path = _POLICY_PATH.resolve().parents[1] / "config" / "api_keys.json"
    try:
        import json

        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _resolve_key(provider: str, provider_policy: dict) -> str:
    env_names, store_names, legacy_names = _key_names(provider, provider_policy)
    for name in env_names:
        value = os.getenv(name)
        if value:
            return value

    try:
        from core.secret_store import SecretStore

        store = SecretStore(_POLICY_PATH.resolve().parents[1] / "config" / "secrets.json")
        for name in store_names:
            value = store.get(name)
            if value:
                return value
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("SecretStore lookup failed for %s: %s", provider, exc)

    legacy = _read_legacy_keys()
    for name in legacy_names:
        value = legacy.get(name)
        if value:
            if provider not in _LEGACY_WARNED:
                _LOGGER.warning(
                    "Using legacy API-key config for %s; migrate it to SecretStore or environment.",
                    provider,
                )
                _LEGACY_WARNED.add(provider)
            return str(value)
    return ""


def _transient(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(word in message for word in _TRANSIENT_WORDS)


def _estimate_tokens(value: Any) -> int:
    if isinstance(value, str):
        return (len(value) + 3) // 4
    if isinstance(value, dict):
        return sum(_estimate_tokens(key) + _estimate_tokens(item)
                   for key, item in value.items())
    if isinstance(value, (tuple, list)):
        return sum(_estimate_tokens(item) for item in value)
    return 0


class LLMEngine:
    def __init__(self, policy: dict | None = None, adapters: dict | None = None):
        self.policy = policy if policy is not None else _load_policy()
        defaults = self.policy.get("defaults", {})
        self.adapters = {
            "gemini": GeminiAdapter(),
            "ollama": OllamaAdapter(),
            "openai_compat": OpenAICompatAdapter(),
            "deepseek": DeepSeekAdapter(),
            "none": NoopAdapter(),
        }
        if adapters:
            self.adapters.update(adapters)
        self._default_timeout = float(defaults.get("timeout_seconds", 45))
        budget = self.policy.get("budget", {})
        llm_budget.set_limits(
            max_tokens_session=int(budget.get("max_tokens_session", 0)),
            max_cost_day=float(budget.get("max_cost_day", 0)),
            warn_ratio=float(budget.get("warn_ratio", 0.8)),
        )

    def register_adapter(self, provider: str, adapter: Any) -> None:
        if not provider or not callable(getattr(adapter, "chat", None)):
            raise ValueError("An adapter needs a provider name and a chat method.")
        with _LOCK:
            self.adapters[provider] = adapter

    def _route(self, role: str) -> tuple[str, str, dict, Any]:
        role_policy = self.policy.get("roles", {}).get(role)
        if not isinstance(role_policy, dict):
            raise LLMConfigError(f"No LLM policy configured for role {role!r}.")
        provider = role_policy.get("provider")
        provider_policy = self.policy.get("providers", {}).get(provider, {})
        if provider == "none":
            raise NotImplementedError("embed non configurato: vedi TODO ADAPTER-EMBED")
        adapter = self.adapters.get(provider)
        if adapter is None:
            raise LLMConfigError(f"No adapter registered for provider {provider!r}.")
        model = role_policy.get("model")
        model_env = role_policy.get("model_env")
        if model_env:
            model = os.getenv(model_env) or model
            if not model and provider == "ollama":
                from core.brain_router import resolve_ollama_model

                model = resolve_ollama_model()
        model = model or provider_policy.get("default_model")
        if not model:
            raise LLMConfigError(f"No model configured for role {role!r}.")
        return provider, str(model), provider_policy, adapter

    def _call_metadata(self, role: str, provider: str, model: str, trace: dict) -> dict:
        return {
            "trace_id": trace["trace_id"],
            "provider": provider,
            "model": model,
            "role": role,
            **{key: trace[key] for key in ("module", "tool", "agent", "session") if key in trace},
        }

    def _execute(
        self,
        method: str,
        messages: list[dict],
        *,
        role: str,
        schema: dict | None = None,
        images: list[Any] | None = None,
        **kw: Any,
    ) -> Any:
        provider, model, provider_policy, adapter = self._route(role)
        status = llm_budget.check_budget()
        context = get_context()
        context.setdefault("trace_id", uuid.uuid4().hex)
        timeout = float(kw.pop("timeout", self._default_timeout))
        generation_defaults = self.policy.get("defaults", {})
        temperature = kw.pop("temperature", generation_defaults.get("temperature", 0.4))
        max_output_tokens = kw.pop(
            "max_output_tokens", generation_defaults.get("max_output_tokens", 2048)
        )
        retries = int(self.policy.get("defaults", {}).get("retries", 2))
        retries = max(0, min(retries, 2))
        with with_context(**context):
            metadata = self._call_metadata(role, provider, model, context)
            llm_events.publish("llm.request", {**metadata, "ok": True})
            if status == "exceeded":
                llm_events.publish("llm.budget_exceeded", {**metadata, "ok": False})
                llm_events.publish(
                    "llm.error",
                    {**metadata, "ok": False, "error_code": LLMBudgetExceeded.error_code},
                )
                raise LLMBudgetExceeded("LLM usage budget exceeded.")
            if status == "warning":
                llm_events.publish("llm.budget_warning", {**metadata, "ok": True})

            started = time.perf_counter()
            try:
                api_key = ""
                requires_key = provider in ("gemini", "deepseek") or bool(
                    getattr(adapter, "requires_key", lambda: False)()
                )
                if requires_key:
                    api_key = _resolve_key(provider, provider_policy)
                    if not api_key:
                        raise LLMAuthError(
                            f"No API key configured for provider {provider!r}."
                        )
                call_kw = {
                    **kw,
                    "timeout": timeout,
                    "api_key": api_key,
                    "role": role,
                    "tier": self.policy.get("roles", {}).get(role, {}).get("tier"),
                    "temperature": temperature,
                    "max_output_tokens": max_output_tokens,
                }
                for attempt in range(retries + 1):
                    try:
                        if method == "chat":
                            result = adapter.chat(messages, model, **call_kw)
                        elif method == "json":
                            json_method = getattr(adapter, "json", None)
                            if not callable(json_method):
                                raise NotImplementedError(
                                    f"Provider {provider!r} does not expose schema-constrained JSON."
                                )
                            result = json_method(messages, schema, model, **call_kw)
                        elif method == "vision":
                            vision_method = getattr(adapter, "vision", None)
                            if not callable(vision_method):
                                raise NotImplementedError(
                                    f"Provider {provider!r} does not expose vision."
                                )
                            result = vision_method(messages, images or [], model, **call_kw)
                        else:
                            raise LLMConfigError(f"Unsupported LLM operation: {method}")
                        if not isinstance(result, (str, dict)):
                            raise LLMError(f"Adapter returned unsupported {method} result.")
                        elapsed_ms = int((time.perf_counter() - started) * 1000)
                        input_tokens = _estimate_tokens(messages)
                        output_tokens = _estimate_tokens(result)
                        llm_budget.track_usage(
                            model, provider, input_tokens, output_tokens
                        )
                        llm_events.publish(
                            "llm.response",
                            {
                                **metadata,
                                "tokens": input_tokens + output_tokens,
                                "input_tokens": input_tokens,
                                "output_tokens": output_tokens,
                                "ms": elapsed_ms,
                                "ok": True,
                            },
                        )
                        post_status = llm_budget.check_budget()
                        if post_status in ("warning", "exceeded"):
                            llm_events.publish(
                                f"llm.budget_{post_status}",
                                {
                                    **metadata,
                                    "tokens": input_tokens + output_tokens,
                                    "ok": post_status != "exceeded",
                                },
                            )
                        return result
                    except (LLMAuthError, LLMBudgetExceeded):
                        raise
                    except Exception as exc:
                        if attempt < retries and _transient(exc):
                            time.sleep(min(0.1 * (2**attempt), 0.4))
                            continue
                        raise
            except Exception as exc:
                llm_events.publish(
                    "llm.error",
                    {
                        **metadata,
                        "ms": int((time.perf_counter() - started) * 1000),
                        "ok": False,
                        "error_code": getattr(exc, "error_code", type(exc).__name__),
                    },
                )
                raise

    def chat(self, messages: list[dict], *, role: str = "chat", **kw: Any) -> str:
        return self._execute("chat", messages, role=role, **kw)

    def json(
        self, messages: list[dict], schema: dict, *, role: str = "json", **kw: Any
    ) -> dict:
        return self._execute("json", messages, role=role, schema=schema, **kw)

    def vision(
        self, messages: list[dict], images: list[Any], *, role: str = "vision", **kw: Any
    ) -> str:
        return self._execute(
            "vision", messages, role=role, images=images, **kw
        )

    def stream(self, messages: list[dict], *, role: str = "chat", **kw: Any) -> Iterator[str]:
        for event in self.stream_events(messages, role=role, **kw):
            if event.get("type") == "content" and event.get("text"):
                yield event["text"]
            elif event.get("type") == "tool_call":
                raise NotImplementedError(
                    "Use stream_events() to receive tool calls."
                )

    def stream_events(
        self, messages: list[dict], *, role: str = "chat", **kw: Any
    ) -> Iterator[dict]:
        provider, model, provider_policy, adapter = self._route(role)
        context = get_context()
        context.setdefault("trace_id", uuid.uuid4().hex)
        timeout = float(kw.pop("timeout", self._default_timeout))
        generation_defaults = self.policy.get("defaults", {})
        temperature = kw.pop("temperature", generation_defaults.get("temperature", 0.4))
        max_output_tokens = kw.pop(
            "max_output_tokens", generation_defaults.get("max_output_tokens", 2048)
        )
        status = llm_budget.check_budget(context.get("session"))
        metadata = self._call_metadata(role, provider, model, context)
        llm_events.publish("llm.stream_start", {**metadata, "ok": True})
        if status == "exceeded":
            llm_events.publish("llm.budget_exceeded", {**metadata, "ok": False})
            llm_events.publish(
                "llm.error",
                {**metadata, "ok": False, "error_code": LLMBudgetExceeded.error_code},
            )
            llm_events.publish("llm.stream_end", {**metadata, "ok": False})
            raise LLMBudgetExceeded("LLM usage budget exceeded.")
        if status == "warning":
            llm_events.publish("llm.budget_warning", {**metadata, "ok": True})
        started = time.perf_counter()
        text_parts = []
        ended = False
        try:
            api_key = ""
            requires_key = provider in ("gemini", "deepseek") or bool(
                getattr(adapter, "requires_key", lambda: False)()
            )
            if requires_key:
                api_key = _resolve_key(provider, provider_policy)
                if not api_key:
                    raise LLMAuthError(
                        f"No API key configured for provider {provider!r}."
                    )
            stream_method = getattr(adapter, "stream_events", None)
            if not callable(stream_method):
                stream_method = getattr(adapter, "stream", None)
            if not callable(stream_method):
                raise NotImplementedError(
                    f"Provider {provider!r} does not expose streaming."
                )
            source = stream_method(
                messages,
                model,
                timeout=timeout,
                api_key=api_key,
                role=role,
                tier=self.policy.get("roles", {}).get(role, {}).get("tier"),
                temperature=temperature,
                max_output_tokens=max_output_tokens,
                **kw,
            )
            iterator = iter(source)
            while True:
                try:
                    with with_context(**context):
                        item = next(iterator)
                except StopIteration:
                    break
                event = item if isinstance(item, dict) else {
                    "type": "content",
                    "text": str(item),
                }
                text = event.get("text", "")
                if event.get("type") == "content" and text:
                    text_parts.append(text)
                llm_events.publish(
                    "llm.stream_chunk",
                    {**metadata, "tokens": _estimate_tokens(text), "ok": True},
                )
                yield event
            input_tokens = _estimate_tokens(messages)
            output_tokens = _estimate_tokens(text_parts)
            with with_context(**context):
                llm_budget.track_usage(model, provider, input_tokens, output_tokens)
            llm_events.publish(
                "llm.stream_end",
                {
                    **metadata,
                    "tokens": input_tokens + output_tokens,
                    "ms": int((time.perf_counter() - started) * 1000),
                    "ok": True,
                },
            )
            ended = True
        except Exception as exc:
            llm_events.publish(
                "llm.error",
                {
                    **metadata,
                    "ms": int((time.perf_counter() - started) * 1000),
                    "ok": False,
                    "error_code": getattr(exc, "error_code", type(exc).__name__),
                },
            )
            llm_events.publish("llm.stream_end", {**metadata, "ok": False})
            ended = True
            raise
        finally:
            if not ended:
                llm_events.publish("llm.stream_end", {**metadata, "ok": False})

    def embed(self, texts: list[str], *, role: str = "embed", **kw: Any) -> list[list[float]]:
        del texts, kw
        self._route(role)
        raise NotImplementedError("embed non configurato: vedi TODO ADAPTER-EMBED")

    def health(self) -> dict:
        providers = {}
        for name, adapter in self.adapters.items():
            try:
                health = adapter.health()
                role_config = next(
                    (
                        self.policy.get("roles", {}).get(role, {})
                        for role in self.policy.get("roles", {})
                        if self.policy.get("roles", {}).get(role, {}).get("provider") == name
                    ),
                    {},
                )
                provider_policy = self.policy.get("providers", {}).get(name, {})
                requires_key = name in ("gemini", "deepseek") or bool(
                    getattr(adapter, "requires_key", lambda: False)()
                )
                if requires_key and not _resolve_key(name, provider_policy):
                    health = {**health, "ok": False, "error_code": LLMAuthError.error_code}
                if (
                    name == "ollama"
                    and role_config.get("model_env")
                    and not os.getenv(role_config["model_env"])
                ):
                    from core.brain_router import resolve_ollama_model

                    health = {**health, "model": resolve_ollama_model()}
                providers[name] = health
            except Exception as exc:  # noqa: BLE001
                _LOGGER.warning("LLM health check failed for %s: %s", name, exc)
                providers[name] = {
                    "provider": name,
                    "ok": False,
                    "error_code": type(exc).__name__,
                }
        return {"ok": True, "roles": sorted(self.policy.get("roles", {})),
                "providers": providers}


llm = LLMEngine()
_default_llm = llm


def get_llm() -> LLMEngine:
    global llm
    with _LOCK:
        if not isinstance(llm, LLMEngine):
            llm = _default_llm
        return llm
