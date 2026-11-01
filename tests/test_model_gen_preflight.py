import asyncio
from types import SimpleNamespace

import pytest

from actions import generate_3d_model as action
from core import local_3d_gen, local_3d_worker, model_gen


def test_tripo_preflight_rejects_missing_key_and_sdk(monkeypatch):
    monkeypatch.setattr(model_gen, "tripo_available", lambda: True)
    monkeypatch.setattr(model_gen, "tripo_key", lambda: "")
    assert model_gen.is_backend_available("tripo") == (False, "no key")

    monkeypatch.setattr(model_gen, "tripo_key", lambda: "test-key")
    monkeypatch.setattr(model_gen, "tripo_available", lambda: False)
    assert model_gen.is_backend_available("tripo") == (False, "Tripo SDK unavailable")


@pytest.mark.parametrize(
    ("balance", "expected"),
    [(0, (False, "no credits")), (2.5, (True, "available"))],
)
def test_tripo_preflight_reads_balance(monkeypatch, balance, expected):
    async def read_balance(key):
        assert key == "test-key"
        return SimpleNamespace(balance=balance, frozen=0)

    monkeypatch.setattr(model_gen, "tripo_available", lambda: True)
    monkeypatch.setattr(model_gen, "tripo_key", lambda: "test-key")
    monkeypatch.setattr(model_gen, "_read_tripo_balance", read_balance)
    assert model_gen.is_backend_available("tripo") == expected


def test_tripo_preflight_marks_unsupported_or_unreadable_balance_unverified(monkeypatch):
    async def no_balance_endpoint(key):
        return None

    monkeypatch.setattr(model_gen, "tripo_available", lambda: True)
    monkeypatch.setattr(model_gen, "tripo_key", lambda: "test-key")
    monkeypatch.setattr(model_gen, "_read_tripo_balance", no_balance_endpoint)
    assert model_gen.is_backend_available("tripo") == (
        True,
        "unverified: balance check unsupported by installed Tripo SDK",
    )

    async def unreadable_balance(key):
        return object()

    monkeypatch.setattr(model_gen, "_read_tripo_balance", unreadable_balance)
    available, reason = model_gen.is_backend_available("tripo")
    assert available is True and reason.startswith("unverified:")


def test_tripo_preflight_timeout_is_bounded_and_marks_backend_unavailable(monkeypatch):
    async def slow_balance(key):
        await asyncio.sleep(0.1)
        return SimpleNamespace(balance=1, frozen=0)

    monkeypatch.setattr(model_gen, "tripo_available", lambda: True)
    monkeypatch.setattr(model_gen, "tripo_key", lambda: "test-key")
    monkeypatch.setattr(model_gen, "TRIPO_PREFLIGHT_TIMEOUT", 0.001)
    monkeypatch.setattr(model_gen, "_read_tripo_balance", slow_balance)
    assert model_gen.is_backend_available("tripo") == (
        False,
        "Tripo balance check timed out",
    )


def test_local_preflight_checks_configured_worker_dependencies(monkeypatch):
    monkeypatch.setattr(local_3d_gen, "is_installed", lambda: True)
    monkeypatch.setattr(local_3d_gen, "configured_backend", lambda: "triposr")
    monkeypatch.setattr(local_3d_worker, "_missing_modules", lambda: [])
    assert model_gen.is_backend_available("local") == (True, "available")

    monkeypatch.setattr(local_3d_worker, "_missing_modules", lambda: ["diffusers"])
    available, reason = model_gen.is_backend_available("local")
    assert available is False and "diffusers" in reason


def test_unavailable_tripo_routes_directly_to_local(monkeypatch, tmp_path):
    used = []
    monkeypatch.setattr(model_gen, "backend", lambda: "tripo")
    monkeypatch.setattr(
        model_gen, "is_backend_available",
        lambda backend: (False, "no credits") if backend == "tripo" else (True, "available"),
    )
    monkeypatch.setattr(local_3d_gen, "configured_backend", lambda: "triposr")
    monkeypatch.setattr(
        model_gen,
        "generate_model",
        lambda *args, **kwargs: pytest.fail("remote generation must not start"),
    )
    monkeypatch.setattr(
        local_3d_gen,
        "generate_local",
        lambda prompt, **kwargs: used.append(prompt) or tmp_path / "apple.glb",
    )
    result = action.generate_3d_model({"prompt": "an apple"})
    assert used == ["an apple"]
    assert "generated and saved" in result


def test_credit_error_falls_back_in_same_call_without_prompting(monkeypatch, tmp_path, caplog):
    caplog.set_level("INFO", logger="actions.generate_3d_model")
    used = []
    monkeypatch.setattr(model_gen, "backend", lambda: "tripo")
    monkeypatch.setattr(model_gen, "tripo_key", lambda: "test-key")
    monkeypatch.setattr(model_gen, "is_backend_available", lambda backend: (True, "available"))
    monkeypatch.setattr(local_3d_gen, "configured_backend", lambda: "triposr")
    monkeypatch.setattr(
        model_gen,
        "generate_model",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("Tripo generation failed: insufficient balance")
        ),
    )
    monkeypatch.setattr(
        local_3d_gen,
        "generate_local",
        lambda prompt, **kwargs: used.append(prompt) or tmp_path / "apple.glb",
    )
    result = action.generate_3d_model({"prompt": "an apple"})
    assert used == ["an apple"]
    assert "generated and saved" in result
    assert "Tripo non disponibile: uso TripoSR locale" in caplog.text
    assert "test-key" not in caplog.text


def test_non_credit_tripo_failure_is_not_hidden_by_local_fallback(monkeypatch):
    local_calls = []
    monkeypatch.setattr(model_gen, "backend", lambda: "tripo")
    monkeypatch.setattr(model_gen, "tripo_key", lambda: "test-key")
    monkeypatch.setattr(model_gen, "is_backend_available", lambda backend: (True, "available"))
    monkeypatch.setattr(
        model_gen,
        "generate_model",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("invalid prompt")),
    )
    monkeypatch.setattr(
        local_3d_gen, "generate_local",
        lambda *args, **kwargs: local_calls.append(True),
    )
    result = action.generate_3d_model({"prompt": "an apple"})
    assert result.startswith("3D generation failed (Tripo engine): invalid prompt")
    assert local_calls == []


def test_tripo_balance_classifier_is_specific():
    assert model_gen.is_credit_error(RuntimeError("Insufficient balance"))
    assert model_gen.is_credit_error(RuntimeError("HTTP 402 payment required"))
    assert not model_gen.is_credit_error(RuntimeError("invalid prompt"))
