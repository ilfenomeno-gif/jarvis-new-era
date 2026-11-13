import logging

from google.genai import types

from core.voice_transport import live_audio_data


def test_live_audio_ignores_text_and_thoughts_without_sdk_warning(caplog):
    response = types.LiveServerMessage(
        server_content=types.LiveServerContent(
            model_turn=types.Content(parts=[
                types.Part(text="private thought", thought=True),
                types.Part(text="response"),
                types.Part(inline_data=types.Blob(data=b"first", mime_type="audio/pcm")),
                types.Part(inline_data=types.Blob(data=b"second", mime_type="audio/pcm")),
            ])
        )
    )
    with caplog.at_level(logging.WARNING):
        assert live_audio_data(response) == b"firstsecond"
    assert not caplog.records


def test_live_audio_no_model_turn():
    assert live_audio_data(types.LiveServerMessage()) == b""
