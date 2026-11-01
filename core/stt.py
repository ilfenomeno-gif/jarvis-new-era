"""
Speech-to-Text engines for MARK XL.

Whisper  – offline transcription via faster-whisper (VAD-buffered)
Vosk     – offline streaming transcription (lighter)
"""
import json
import threading
import numpy as np


def whisper_available() -> bool:
    """True when faster-whisper is importable (checked without loading it)."""
    import importlib.util
    return importlib.util.find_spec("faster_whisper") is not None


WHISPER_MISSING_MESSAGE = (
    "Offline dictation is unavailable: install the optional package "
    "'faster-whisper' (pip install -r requirements-optional.txt)."
)


class WhisperSTT:
    """Offline transcription using faster-whisper."""

    def __init__(
        self,
        model_name: str = "base",
        language: str | None = None,
        local_files_only: bool = False,
    ):
        import os
        from faster_whisper import WhisperModel
        print(f"[STT] Loading Whisper '{model_name}'…")
        try:
            import torch
            device  = "cuda" if torch.cuda.is_available() else "cpu"
            compute = "float16" if device == "cuda" else "int8"
        except Exception:
            device, compute = "cpu", "int8"

        try:
            self._model = WhisperModel(
                model_name,
                device=device,
                compute_type=compute,
                local_files_only=local_files_only,
            )
        except Exception as _first_err:
            if local_files_only:
                raise RuntimeError(
                    f"Whisper model '{model_name}' is not available in the local cache. "
                    "Download/configure it explicitly before using offline dictation."
                ) from _first_err
            # Offline flag set but model not cached yet → clear flags and download once.
            # Keywords cover multiple huggingface_hub error message variants across versions.
            _e = str(_first_err).lower()
            _offline_keywords = (
                "offline", "not found", "cache", "localentry",
                "does not exist", "outgoing", "local_files_only",
            )
            if any(k in _e for k in _offline_keywords):
                print(f"[STT] Whisper '{model_name}' not in local cache — downloading (one-time, internet required)…")
                os.environ.pop("HF_HUB_OFFLINE",      None)
                os.environ.pop("TRANSFORMERS_OFFLINE", None)
                os.environ.pop("HF_DATASETS_OFFLINE",  None)
                try:
                    self._model = WhisperModel(
                        model_name,
                        device=device,
                        compute_type=compute,
                        local_files_only=False,
                    )
                except Exception as _dl_err:
                    raise RuntimeError(
                        f"Whisper '{model_name}' model download failed.\n"
                        f"Internet access is required the first time to download the speech model (~75–290 MB).\n"
                        f"After the first download it runs fully offline.\n"
                        f"Details: {_dl_err}"
                    ) from _dl_err
            else:
                raise

        self._language = None if (not language or language.strip().lower() == "auto") else language.strip().lower()
        print(f"[STT] Whisper '{model_name}' ready ({device})")

    def transcribe(self, audio: np.ndarray, vad_filter: bool = True) -> str:
        """Transcribe a float32 mono 16 kHz numpy array. Returns transcript string."""
        try:
            segments, _ = self._model.transcribe(
                audio,
                language=self._language,
                beam_size=1,                       # greedy — 2-3x faster
                best_of=1,
                condition_on_previous_text=False,  # no hallucinations, faster
                vad_filter=vad_filter,
                vad_parameters={"min_silence_duration_ms": 300},
            )
            return " ".join(s.text for s in segments).strip()
        except Exception as e:
            print(f"[STT] Transcription error: {e}")
            raise


class DictationBuffer:
    """Bounded, volatile 16 kHz mono audio buffer for explicit dictation."""

    def __init__(self, max_seconds: int = 60, sample_rate: int = 16000) -> None:
        if max_seconds < 1 or sample_rate < 1:
            raise ValueError("Dictation duration and sample rate must be positive")
        self._max_samples = max_seconds * sample_rate
        self._lock = threading.Lock()
        self._frames: list[np.ndarray] = []
        self._sample_count = 0
        self._recording = False

    @property
    def is_recording(self) -> bool:
        with self._lock:
            return self._recording

    def start(self) -> None:
        with self._lock:
            if self._recording:
                raise RuntimeError("Dictation is already recording")
            self._frames.clear()
            self._sample_count = 0
            self._recording = True

    def append(self, frame: np.ndarray) -> bool:
        """Copy one int16 mic frame; stop accepting data at the size limit."""
        with self._lock:
            if not self._recording or self._sample_count >= self._max_samples:
                return False
            samples = np.asarray(frame)
            if samples.ndim > 1:
                samples = samples[:, 0]
            samples = samples.reshape(-1)
            if samples.dtype != np.int16:
                raise TypeError("Dictation audio frames must use int16 samples")

            remaining = self._max_samples - self._sample_count
            if samples.size > remaining:
                samples = samples[:remaining]
            if samples.size:
                self._frames.append(samples.copy())
                self._sample_count += samples.size
            return bool(samples.size)

    def stop(self) -> np.ndarray:
        """End capture, return normalized float32 audio, and clear the buffer."""
        with self._lock:
            self._recording = False
            if not self._frames:
                self._sample_count = 0
                return np.empty(0, dtype=np.float32)
            audio = np.concatenate(self._frames).astype(np.float32) / 32768.0
            self._frames.clear()
            self._sample_count = 0
            return audio

    def discard(self) -> None:
        """End capture and drop buffered audio without transcribing it."""
        with self._lock:
            self._recording = False
            self._frames.clear()
            self._sample_count = 0


def route_microphone_audio(
    frame: np.ndarray,
    dictation_buffer: DictationBuffer,
    wake_word_gate=None,
) -> tuple[bytes, ...]:
    """Keep dictation audio local; otherwise apply the optional wake gate."""
    if dictation_buffer.is_recording:
        dictation_buffer.append(frame)
        return ()
    if wake_word_gate is not None:
        return wake_word_gate.process_frame(frame)
    return (frame.tobytes(),)


class VoskSTT:
    """Streaming transcription using Vosk."""

    def __init__(self, model_path: str | None = None, language: str = "en-us"):
        from vosk import Model, KaldiRecognizer
        print("[STT] Loading Vosk model…")
        if model_path:
            model = Model(model_path)
        else:
            lang  = language.strip().lower() if language and language.strip().lower() != "auto" else "en-us"
            model = Model(lang=lang)
        self._rec = KaldiRecognizer(model, 16000)
        print("[STT] Vosk ready.")

    def process_chunk(self, audio_bytes: bytes) -> tuple[str, bool]:
        """Feed raw int16 LE PCM bytes. Returns (text, is_final)."""
        if self._rec.AcceptWaveform(audio_bytes):
            result = json.loads(self._rec.Result())
            return result.get("text", ""), True
        partial = json.loads(self._rec.PartialResult())
        return partial.get("partial", ""), False
