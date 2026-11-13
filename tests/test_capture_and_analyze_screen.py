import io
import threading
from types import SimpleNamespace

import google.genai
import pytest
from google.genai import types
from PIL import Image

from actions import capture_and_analyze_screen as vision_action
from actions import screen_processor


@pytest.fixture(autouse=True)
def isolate_mocked_vision_in_process(monkeypatch):
    # These unit tests mock Gemini and screen capture in the current process.
    monkeypatch.setattr(vision_action, "_run_isolated", vision_action._capture_and_analyze_screen)
    monkeypatch.setattr(vision_action, "_vision_in_progress", False)
    monkeypatch.setattr(vision_action, "_vision_finished_at", None)
    monkeypatch.setattr(vision_action, "_vision_internal_errors", 0)
    monkeypatch.setattr(
        screen_processor, "_capture_vision_screen",
        lambda _mode="screen": screen_processor._capture_screen(),
    )


def _image_bytes(width=20, height=10):
    output = io.BytesIO()
    Image.new("RGB", (width, height), "blue").save(output, format="PNG")
    return output.getvalue()


@pytest.mark.parametrize("error_fields,detail", [
    ({"code": 500}, "technical server details"),
    ({"status": "INTERNAL"}, "technical server details"),
    ({"details": {"status": "INTERNAL"}}, "technical server details"),
    ({}, "500 INTERNAL technical server details"),
])
def test_internal_server_error_returns_clean_message(monkeypatch, error_fields, detail):
    class InternalError(RuntimeError):
        pass

    def generate_content(**_kwargs):
        error = InternalError(detail)
        for key, value in error_fields.items():
            setattr(error, key, value)
        raise error

    monkeypatch.setattr(google.genai, "Client", lambda **_kwargs: SimpleNamespace(
        models=SimpleNamespace(generate_content=generate_content)
    ))
    monkeypatch.setattr(screen_processor, "_capture_screen", lambda: (_image_bytes(), "image/png"))
    monkeypatch.setattr(screen_processor, "_get_api_key", lambda: "test-api-key")
    assert vision_action.capture_and_analyze_screen() == vision_action.VISION_INTERNAL_MESSAGE


def test_cooldown_and_adaptive_width_apply_across_gemma_requests(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(vision_action, "time", SimpleNamespace(
        monotonic=lambda: now[0], sleep=lambda _seconds: None
    ))
    calls = []
    screenshots = []

    class QuotaError(Exception):
        code = 429

    class InternalError(Exception):
        code = 500

    def generate_content(**kwargs):
        calls.append(kwargs)
        if kwargs["model"] != vision_action.GEMMA_VISION_MODEL:
            raise QuotaError("RESOURCE_EXHAUSTED")
        if len([call for call in calls if call["model"] == vision_action.GEMMA_VISION_MODEL]) <= 2:
            raise InternalError("sensitive technical error")
        return SimpleNamespace(text="Vedo il browser.")

    def screenshot():
        screenshots.append(True)
        return _image_bytes(1600, 900), "image/png"

    monkeypatch.setattr(screen_processor, "_capture_screen", screenshot)
    monkeypatch.setattr(screen_processor, "_get_api_key", lambda: "test-api-key")
    monkeypatch.setattr(google.genai, "Client", lambda **_kwargs: SimpleNamespace(
        models=SimpleNamespace(generate_content=generate_content)
    ))

    assert vision_action.capture_and_analyze_screen() == vision_action.VISION_INTERNAL_MESSAGE
    assert vision_action.capture_and_analyze_screen() == vision_action.VISION_COOLDOWN_MESSAGE
    assert len(screenshots) == 1
    now[0] += 10
    assert vision_action.capture_and_analyze_screen() == vision_action.VISION_INTERNAL_MESSAGE
    now[0] += 10
    assert vision_action.capture_and_analyze_screen() == "Vedo il browser."
    now[0] += 10
    assert vision_action.capture_and_analyze_screen() == "Vedo il browser."
    gemma_calls = [call for call in calls if call["model"] == vision_action.GEMMA_VISION_MODEL]
    widths = [
        Image.open(io.BytesIO(call["contents"][0].inline_data.data)).width
        for call in gemma_calls
    ]
    assert widths == [1024, 1024, 800, 1024]
    assert len(screenshots) == 4


def test_overlapping_vision_requests_are_rejected(monkeypatch):
    started, release = threading.Event(), threading.Event()
    result = []

    def slow_run(_parameters, _player):
        started.set()
        assert release.wait(5)
        return "Analisi."

    monkeypatch.setattr(vision_action, "_run_isolated", slow_run)
    worker = threading.Thread(target=lambda: result.append(vision_action.capture_and_analyze_screen()))
    worker.start()
    try:
        assert started.wait(2)
        assert vision_action.capture_and_analyze_screen() == vision_action.VISION_COOLDOWN_MESSAGE
    finally:
        release.set()
        worker.join(timeout=3)
    assert result == ["Analisi."]
    assert vision_action.capture_and_analyze_screen() == vision_action.VISION_COOLDOWN_MESSAGE


def test_non_500_response_breaks_error_streak(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(vision_action, "time", SimpleNamespace(monotonic=lambda: now[0]))
    responses = iter([
        vision_action.VISION_INTERNAL_MESSAGE,
        vision_action.VISION_QUOTA_MESSAGE,
        vision_action.VISION_INTERNAL_MESSAGE,
        "Analisi.",
    ])
    widths = []

    def run(parameters, _player):
        widths.append(parameters["_vision_max_width"])
        return next(responses)

    monkeypatch.setattr(vision_action, "_run_isolated", run)
    for _ in range(4):
        vision_action.capture_and_analyze_screen()
        now[0] += 10
    assert widths == [1024, 1024, 1024, 1024]


def test_failure_releases_in_progress_and_still_enforces_cooldown(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(vision_action, "time", SimpleNamespace(monotonic=lambda: now[0]))

    def fail(_parameters, _player):
        raise RuntimeError("errore simulato")

    monkeypatch.setattr(vision_action, "_run_isolated", fail)
    with pytest.raises(RuntimeError, match="errore simulato"):
        vision_action.capture_and_analyze_screen()
    assert vision_action.capture_and_analyze_screen() == vision_action.VISION_COOLDOWN_MESSAGE
    now[0] += 10
    monkeypatch.setattr(vision_action, "_run_isolated", lambda *_args: "Analisi.")
    assert vision_action.capture_and_analyze_screen() == "Analisi."


def test_capture_and_analyze_screen_sends_image_to_gemini(monkeypatch):
    screenshot = _image_bytes(2560, 1440)
    captured_requests = []
    client_options = []

    class Models:
        def generate_content(self, **kwargs):
            captured_requests.append(kwargs)
            return SimpleNamespace(text="Vedo una pagina web con un titolo.")

    client = SimpleNamespace(models=Models())

    def create_client(*, api_key, http_options):
        client_options.append((api_key, http_options))
        return client

    monkeypatch.setattr(google.genai, "Client", create_client)
    monkeypatch.setattr(
        "actions.screen_processor._capture_screen",
        lambda: (screenshot, "image/png"),
    )
    monkeypatch.setattr(
        "actions.screen_processor._get_api_key",
        lambda: "test-api-key",
    )

    result = vision_action.capture_and_analyze_screen(
        {"question": "Leggi il titolo"}
    )

    assert result == "Vedo una pagina web con un titolo."
    assert len(captured_requests) == 1
    request = captured_requests[0]
    assert request["model"] == screen_processor.GEMINI_VISION_MODEL
    assert request["model"] == "gemini-3.8-flash"
    assert request["config"].max_output_tokens == 2000
    assert request["config"].thinking_config.thinking_level.value == "LOW"
    image = Image.open(io.BytesIO(request["contents"][0].inline_data.data))
    assert image.size == (1024, 576)
    assert request["contents"][0].inline_data.mime_type == "image/jpeg"
    assert "Leggi il titolo" in request["contents"][1]
    assert "sinistra, destra, centro" in request["contents"][1]
    assert "terminale, del browser" in request["contents"][1]
    assert client_options[0][0] == "test-api-key"
    assert client_options[0][1].timeout == 20_000
    assert client_options[0][1].retry_options.attempts == 1


@pytest.mark.parametrize(("width", "height", "expected"), [
    (400, 200, (400, 200)),
    (1024, 1200, (1024, 1200)),
    (1600, 2400, (1024, 1536)),
])
def test_vision_image_width_limit_preserves_aspect_ratio(monkeypatch, width, height, expected):
    requests = []

    def generate_content(**kwargs):
        requests.append(kwargs)
        return SimpleNamespace(text="Analisi.")

    monkeypatch.setattr(google.genai, "Client", lambda **_kwargs: SimpleNamespace(
        models=SimpleNamespace(generate_content=generate_content)
    ))
    monkeypatch.setattr(screen_processor, "_capture_screen", lambda: (_image_bytes(width, height), "image/png"))
    monkeypatch.setattr(screen_processor, "_get_api_key", lambda: "test-api-key")

    assert vision_action.capture_and_analyze_screen() == "Analisi."
    image = Image.open(io.BytesIO(requests[0]["contents"][0].inline_data.data))
    assert image.size == expected


def test_capture_and_analyze_screen_returns_fallback_for_empty_model_response(monkeypatch):
    class Models:
        def generate_content(self, **_kwargs):
            return SimpleNamespace(text="")

    monkeypatch.setattr(
        google.genai,
        "Client",
        lambda **_kwargs: SimpleNamespace(models=Models()),
    )
    monkeypatch.setattr(
        "actions.screen_processor._capture_screen",
        lambda: (_image_bytes(), "image/png"),
    )
    monkeypatch.setattr(
        "actions.screen_processor._get_api_key",
        lambda: "test-api-key",
    )

    assert vision_action.capture_and_analyze_screen() == (
        "Gemini ha analizzato ma non ha prodotto testo. Riprova."
    )


def test_capture_and_analyze_screen_exposes_and_logs_unauthorized_error(
    monkeypatch, capsys
):
    class UnauthorizedError(RuntimeError):
        status_code = 401

    class Models:
        def generate_content(self, **_kwargs):
            raise UnauthorizedError("API key not valid")

    monkeypatch.setattr(
        google.genai,
        "Client",
        lambda **_kwargs: SimpleNamespace(models=Models()),
    )
    monkeypatch.setattr(
        "actions.screen_processor._capture_screen",
        lambda: (_image_bytes(), "image/png"),
    )
    monkeypatch.setattr(
        "actions.screen_processor._get_api_key",
        lambda: "test-api-key",
    )

    with pytest.raises(RuntimeError, match="Errore API Visione: HTTP 401: API key not valid"):
        vision_action.capture_and_analyze_screen()

    assert "[Vision] Errore API Visione: HTTP 401: API key not valid" in capsys.readouterr().out


def test_gemini_key_uses_environment_before_legacy_config(monkeypatch, tmp_path):
    config_path = tmp_path / "api_keys.json"
    config_path.write_text(
        '{"gemini_api_key": "config-test-key"}',
        encoding="utf-8",
    )
    monkeypatch.setattr(screen_processor, "_CONFIG_PATH", config_path)
    monkeypatch.setattr(screen_processor, "_BASE", tmp_path)
    monkeypatch.setenv("GEMINI_API_KEY", "environment-test-key")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    assert screen_processor._get_api_key() == "environment-test-key"

    monkeypatch.delenv("GEMINI_API_KEY")
    assert screen_processor._get_api_key() == "config-test-key"


def test_capture_and_analyze_screen_reports_missing_gemini_key(monkeypatch):
    def missing_api_key():
        raise RuntimeError("Chiave API Gemini mancante nel file .env.")

    monkeypatch.setattr(
        "actions.screen_processor._capture_screen",
        lambda: (_image_bytes(), "image/png"),
    )
    monkeypatch.setattr("actions.screen_processor._get_api_key", missing_api_key)

    with pytest.raises(
        RuntimeError,
        match="Chiave API Gemini mancante nel file .env",
    ):
        vision_action.capture_and_analyze_screen()


def test_capture_and_analyze_screen_rejects_unsupported_mime_type(monkeypatch):
    monkeypatch.setattr(
        "actions.screen_processor._capture_screen",
        lambda: (b"fake-image-bytes", "application/octet-stream"),
    )

    with pytest.raises(RuntimeError, match="Formato immagine non supportato"):
        vision_action.capture_and_analyze_screen()


@pytest.mark.parametrize("status", [503, 504])
def test_vision_retries_transient_errors_then_succeeds(monkeypatch, status):
    calls = []

    class ServerError(RuntimeError):
        code = status

    class Models:
        def generate_content(self, **_kwargs):
            calls.append(1)
            if len(calls) == 1:
                raise ServerError("server unavailable")
            return SimpleNamespace(text="Vedo una finestra.")

    monkeypatch.setattr(google.genai, "Client", lambda **_kwargs: SimpleNamespace(models=Models()))
    monkeypatch.setattr(screen_processor, "_capture_screen", lambda: (_image_bytes(), "image/png"))
    monkeypatch.setattr(screen_processor, "_get_api_key", lambda: "test-api-key")
    monkeypatch.setattr(vision_action.time, "sleep", lambda _seconds: None)

    assert vision_action.capture_and_analyze_screen() == "Vedo una finestra."
    assert len(calls) == 2


def test_vision_reports_slow_server_after_three_timeouts(monkeypatch):
    calls = []

    class DeadlineError(RuntimeError):
        code = 504

    class Models:
        def generate_content(self, **_kwargs):
            calls.append(1)
            raise DeadlineError("deadline exceeded")

    monkeypatch.setattr(google.genai, "Client", lambda **_kwargs: SimpleNamespace(models=Models()))
    monkeypatch.setattr(screen_processor, "_capture_screen", lambda: (_image_bytes(), "image/png"))
    monkeypatch.setattr(screen_processor, "_get_api_key", lambda: "test-api-key")
    monkeypatch.setattr(vision_action.time, "sleep", lambda _seconds: None)

    assert vision_action.capture_and_analyze_screen() == vision_action.VISION_SLOW_MESSAGE
    assert len(calls) == 3


@pytest.mark.parametrize("error_fields", [
    {"code": 429},
    {"status": "RESOURCE_EXHAUSTED"},
    {"details": {"status": "RESOURCE_EXHAUSTED"}},
])
def test_vision_quota_error_returns_clean_message(monkeypatch, error_fields):
    class QuotaError(RuntimeError):
        pass

    calls = []

    class Models:
        def generate_content(self, **kwargs):
            calls.append(kwargs["model"])
            error = QuotaError("429 RESOURCE_EXHAUSTED: technical details")
            for key, value in error_fields.items():
                setattr(error, key, value)
            raise error

    monkeypatch.setattr(google.genai, "Client", lambda **_kwargs: SimpleNamespace(models=Models()))
    monkeypatch.setattr(screen_processor, "_capture_screen", lambda: (_image_bytes(), "image/png"))
    monkeypatch.setattr(screen_processor, "_get_api_key", lambda: "test-api-key")
    assert vision_action.capture_and_analyze_screen() == (
        "Signore, ho esaurito le mie richieste per l'analisi visiva. Riprovo tra qualche minuto."
    )
    assert calls == [screen_processor.GEMINI_VISION_MODEL, "gemma-4-26b-a4b-it"]


def test_vision_429_falls_back_to_gemma_with_same_payload(monkeypatch):
    calls = []
    client_options = []

    class QuotaError(RuntimeError):
        code = 429

    class Models:
        def generate_content(self, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                raise QuotaError("RESOURCE_EXHAUSTED")
            return SimpleNamespace(text="Vedo il browser.")

    def create_client(**kwargs):
        client_options.append(kwargs["http_options"])
        return SimpleNamespace(models=Models())

    monkeypatch.setattr(google.genai, "Client", create_client)
    monkeypatch.setattr(screen_processor, "_capture_screen", lambda: (_image_bytes(), "image/png"))
    monkeypatch.setattr(screen_processor, "_get_api_key", lambda: "test-api-key")

    assert vision_action.capture_and_analyze_screen({"question": "Cosa vedi?"}) == "Vedo il browser."
    assert [call["model"] for call in calls] == [
        screen_processor.GEMINI_VISION_MODEL, "gemma-4-26b-a4b-it",
    ]
    assert calls[0]["contents"] == calls[1]["contents"]
    assert calls[0]["config"].max_output_tokens == calls[1]["config"].max_output_tokens == 2000
    assert calls[0]["config"].thinking_config.thinking_level.value == "LOW"
    assert calls[1]["config"].thinking_config is None
    assert [options.timeout for options in client_options] == [20_000, 45_000]
    assert all(options.retry_options.attempts == 1 for options in client_options)


def test_vision_fallback_error_reports_gemma_error(monkeypatch, caplog):
    class QuotaError(RuntimeError):
        code = 429

    class MissingModel(RuntimeError):
        code = 404

    class Models:
        def generate_content(self, **kwargs):
            if kwargs["model"] == screen_processor.GEMINI_VISION_MODEL:
                raise QuotaError("primary quota")
            raise MissingModel("Gemma model unavailable")

    monkeypatch.setattr(google.genai, "Client", lambda **_kwargs: SimpleNamespace(models=Models()))
    monkeypatch.setattr(screen_processor, "_capture_screen", lambda: (_image_bytes(), "image/png"))
    monkeypatch.setattr(screen_processor, "_get_api_key", lambda: "test-api-key")

    with pytest.raises(RuntimeError, match="gemma-4-26b-a4b-it.*404.*Gemma model unavailable"):
        vision_action.capture_and_analyze_screen()
    assert "Gemma model unavailable" in caplog.text


@pytest.mark.parametrize(("fallback_status", "expected"), [
    (429, vision_action.VISION_QUOTA_MESSAGE),
    (503, vision_action.VISION_OVERLOAD_MESSAGE),
    (504, vision_action.VISION_SLOW_MESSAGE),
])
def test_vision_reports_actual_fallback_failure(monkeypatch, caplog, fallback_status, expected):
    models = []

    class Models:
        def generate_content(self, **kwargs):
            models.append(kwargs["model"])
            status = 429 if len(models) == 1 else fallback_status
            raise RuntimeError(f"HTTP {status}: failure from {kwargs['model']}")

    monkeypatch.setattr(google.genai, "Client", lambda **_kwargs: SimpleNamespace(models=Models()))
    monkeypatch.setattr(screen_processor, "_capture_screen", lambda: (_image_bytes(), "image/png"))
    monkeypatch.setattr(screen_processor, "_get_api_key", lambda: "test-api-key")

    assert vision_action.capture_and_analyze_screen() == expected
    assert models == [screen_processor.GEMINI_VISION_MODEL, vision_action.GEMMA_VISION_MODEL]
    assert f"HTTP {fallback_status}: failure from {vision_action.GEMMA_VISION_MODEL}" in caplog.text


def test_vision_process_timeout_returns_clean_message(monkeypatch):
    def timeout(*_args):
        raise TimeoutError("technical process timeout")

    monkeypatch.setattr(vision_action, "_run_isolated", timeout)
    assert vision_action.capture_and_analyze_screen() == vision_action.VISION_SLOW_MESSAGE


@pytest.mark.parametrize("fallback_fails", [False, True])
def test_vision_503_backoff_then_fallback(monkeypatch, fallback_fails):
    models = []
    delays = []
    client_options = []

    class ServerError(RuntimeError):
        code = 503

    class Models:
        def generate_content(self, **kwargs):
            models.append(kwargs["model"])
            if len(models) <= 3 or fallback_fails:
                raise ServerError("overloaded")
            return SimpleNamespace(text="Vedo una finestra.")

    def create_client(**kwargs):
        client_options.append(kwargs["http_options"])
        return SimpleNamespace(models=Models())

    monkeypatch.setattr(google.genai, "Client", create_client)
    monkeypatch.setattr(screen_processor, "_capture_screen", lambda: (_image_bytes(), "image/png"))
    monkeypatch.setattr(screen_processor, "_get_api_key", lambda: "test-api-key")
    monkeypatch.setattr(vision_action.time, "sleep", delays.append)

    result = vision_action.capture_and_analyze_screen()
    assert result == (
        vision_action.VISION_OVERLOAD_MESSAGE if fallback_fails else "Vedo una finestra."
    )
    assert models == [screen_processor.GEMINI_VISION_MODEL] * 3 + [vision_action.GEMMA_VISION_MODEL]
    assert delays == [1, 2, 4]
    assert [options.timeout for options in client_options] == [20_000, 45_000]


def test_vision_third_primary_attempt_succeeds_without_fallback(monkeypatch):
    models, delays = [], []

    class ServerError(RuntimeError):
        code = 503

    class Models:
        def generate_content(self, **kwargs):
            models.append(kwargs["model"])
            if len(models) < 3:
                raise ServerError("overloaded")
            return SimpleNamespace(text="Successo.")

    monkeypatch.setattr(google.genai, "Client", lambda **_kwargs: SimpleNamespace(models=Models()))
    monkeypatch.setattr(screen_processor, "_capture_screen", lambda: (_image_bytes(), "image/png"))
    monkeypatch.setattr(screen_processor, "_get_api_key", lambda: "test-api-key")
    monkeypatch.setattr(vision_action.time, "sleep", delays.append)
    assert vision_action.capture_and_analyze_screen() == "Successo."
    assert models == [screen_processor.GEMINI_VISION_MODEL] * 3
    assert delays == [1, 2]


def test_plain_speech_text_strips_markdown():
    from actions.capture_and_analyze_screen import plain_speech_text

    assert plain_speech_text("Vedo **VS Code**:\n* uno\n* due") == "Vedo VS Code: uno. due"


def test_vision_concatenates_text_parts_without_thoughts(monkeypatch):
    response = types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(parts=[
                    types.Part(text="Ragionamento privato", thought=True),
                    types.Part(text="Vedo **una finestra**"),
                    types.Part(text=" aperta."),
                ])
            )
        ]
    )
    monkeypatch.setattr(
        google.genai, "Client",
        lambda **_kwargs: SimpleNamespace(
            models=SimpleNamespace(generate_content=lambda **_kwargs: response)
        ),
    )
    monkeypatch.setattr(screen_processor, "_capture_screen", lambda: (_image_bytes(), "image/png"))
    monkeypatch.setattr(screen_processor, "_get_api_key", lambda: "test-api-key")

    assert vision_action.capture_and_analyze_screen() == "Vedo una finestra aperta."


def test_vision_only_thought_uses_last_nonempty_thought_without_logging_it(monkeypatch, capsys, caplog):
    response = types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(parts=[
            types.Part(text="Pensiero precedente", thought=True),
            types.Part(text="**Vedo** una finestra.", thought=True),
            types.Part(text=" ", thought=True),
        ]))]
    )
    monkeypatch.setattr(
        google.genai, "Client",
        lambda **_kwargs: SimpleNamespace(
            models=SimpleNamespace(generate_content=lambda **_kwargs: response)
        ),
    )
    monkeypatch.setattr(screen_processor, "_capture_screen", lambda: (_image_bytes(), "image/png"))
    monkeypatch.setattr(screen_processor, "_get_api_key", lambda: "test-api-key")

    result = vision_action.capture_and_analyze_screen()
    assert result == "Vedo una finestra."
    output = capsys.readouterr().out
    assert "Vedo" not in output
    assert "Pensiero precedente" not in output
    assert "unverified fallback" in caplog.text


def test_vision_parts_are_preferred_over_unsafe_response_text(capsys):
    class Response:
        candidates = [SimpleNamespace(content=SimpleNamespace(parts=[
            SimpleNamespace(text="Segreto", thought=True),
            SimpleNamespace(text="Vedo ", thought=False),
            SimpleNamespace(text="la pagina.", thought=False),
        ]))]

        @property
        def text(self):
            pytest.fail("response.text could include thought content")

    assert vision_action.extract_vision_text(Response()) == "Vedo la pagina."
    output = capsys.readouterr().out
    assert "[Vision] Risposta: Vedo la pagina." in output
    assert "Segreto" not in output


@pytest.mark.parametrize("response", [
    types.GenerateContentResponse(candidates=[]),
    types.GenerateContentResponse(candidates=[types.Candidate(content=None)]),
    types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(parts=[]))]),
])
def test_vision_missing_parts_returns_empty_text(response, capsys):
    assert vision_action.extract_vision_text(response) == ""
    assert "[Vision] Risposta:" in capsys.readouterr().out


def test_vision_invalid_response_format_is_reported():
    response = SimpleNamespace(candidates=[SimpleNamespace(content=object())])
    with pytest.raises(RuntimeError, match="Formato della risposta Gemini Vision"):
        vision_action.extract_vision_text(response)


def test_progress_is_immediate_warns_after_20_seconds_and_stops(monkeypatch):
    messages = []
    timers = []

    class Timer:
        def __init__(self, interval, callback):
            self.interval = interval
            self.callback = callback
            self.cancelled = False
            timers.append(self)

        def start(self):
            pass

        def cancel(self):
            self.cancelled = True

    monkeypatch.setattr(vision_action.threading, "Timer", Timer)
    player = SimpleNamespace(write_log=messages.append)
    with vision_action._vision_progress(player):
        assert messages == [vision_action.VISION_START_MESSAGE]
        assert timers[0].interval == 20.0
        timers[0].callback()
        assert messages[-1] == vision_action.VISION_PROGRESS_MESSAGE

    assert timers[0].cancelled
    timers[0].callback()
    assert messages == [vision_action.VISION_START_MESSAGE, vision_action.VISION_PROGRESS_MESSAGE]


def test_progress_timer_cancelled_on_failure(monkeypatch):
    timers = []

    class Timer:
        def __init__(self, interval, callback):
            self.callback = callback
            self.cancelled = False
            timers.append(self)

        def start(self):
            pass

        def cancel(self):
            self.cancelled = True

    monkeypatch.setattr(vision_action.threading, "Timer", Timer)
    player = SimpleNamespace(write_log=lambda _message: None)
    with pytest.raises(ValueError):
        with vision_action._vision_progress(player):
            raise ValueError("failure")
    assert timers[0].cancelled


def test_screen_command_displays_progress_and_speaks_parsed_result(monkeypatch):
    import main

    messages = []
    spoken = []
    done = threading.Event()
    response = types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(parts=[
            types.Part(text="thought", thought=True),
            types.Part(text="Vedo "),
            types.Part(text="il browser."),
        ]))]
    )
    monkeypatch.setattr(
        google.genai, "Client",
        lambda **_kwargs: SimpleNamespace(
            models=SimpleNamespace(generate_content=lambda **_kwargs: response)
        ),
    )
    monkeypatch.setattr(screen_processor, "_capture_screen", lambda: (_image_bytes(), "image/png"))
    monkeypatch.setattr(screen_processor, "_get_api_key", lambda: "test-api-key")

    class Registry:
        def run(self, _name, parameters, ctx):
            return vision_action.capture_and_analyze_screen(parameters, **ctx)

    live = object.__new__(main.JarvisLive)
    live._action_registry = Registry()
    live._asst_name = "Jarvis"
    live.ui = SimpleNamespace(write_log=lambda message: messages.append(("log", message)))
    live._hud = SimpleNamespace(push_chat=lambda role, message: messages.append((role, message)))
    live._set_task_idle = lambda _idle: None
    live.session = object()
    live._loop = object()
    live.speak = lambda message: (spoken.append(message), done.set())

    assert live._schedule_screen_analysis("cosa vedi")
    assert done.wait(3)
    assert ("log", vision_action.VISION_START_MESSAGE) in messages
    assert ("assistant", "Vedo il browser.") in messages
    assert spoken[0].endswith("Vedo il browser.")


def test_screen_command_displays_and_speaks_thought_fallback(monkeypatch):
    import main

    messages = []
    spoken = []
    done = threading.Event()
    response = types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(parts=[
            types.Part(text="**Vedo** il browser.", thought=True),
        ]))]
    )
    monkeypatch.setattr(
        google.genai, "Client",
        lambda **_kwargs: SimpleNamespace(
            models=SimpleNamespace(generate_content=lambda **_kwargs: response)
        ),
    )
    monkeypatch.setattr(screen_processor, "_capture_screen", lambda: (_image_bytes(), "image/png"))
    monkeypatch.setattr(screen_processor, "_get_api_key", lambda: "test-api-key")

    class Registry:
        def run(self, _name, parameters, ctx):
            return vision_action.capture_and_analyze_screen(parameters, **ctx)

    live = object.__new__(main.JarvisLive)
    live._action_registry = Registry()
    live._asst_name = "Jarvis"
    live.ui = SimpleNamespace(write_log=lambda message: messages.append(("log", message)))
    live._hud = SimpleNamespace(push_chat=lambda role, message: messages.append((role, message)))
    live._set_task_idle = lambda _idle: None
    live.session = object()
    live._loop = object()
    live.speak = lambda message: (spoken.append(message), done.set())

    assert live._schedule_screen_analysis("cosa vedi")
    assert done.wait(3)
    assert ("assistant", "Vedo il browser.") in messages
    assert spoken[0].endswith("Vedo il browser.")
