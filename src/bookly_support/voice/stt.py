"""English transcripts for the desk. The model does not answer the customer."""

from __future__ import annotations

import threading

import numpy as np

_lock = threading.Lock()
_model = None


def get_whisper():
    global _model
    if _model is not None:
        return _model
    with _lock:
        if _model is None:
            from faster_whisper import WhisperModel

            from bookly_support.voice.models import WHISPER_MODEL, whisper_dir

            whisper_dir().mkdir(parents=True, exist_ok=True)
            _model = WhisperModel(
                WHISPER_MODEL,
                device="cpu",
                compute_type="int8",
                download_root=str(whisper_dir()),
                cpu_threads=4,
            )
        return _model


def transcribe(samples: np.ndarray) -> str:
    """Force English. An empty room stays an empty string."""

    audio = np.asarray(samples, dtype=np.float32).reshape(-1)
    if audio.size == 0:
        return ""
    model = get_whisper()
    with _lock:
        segments, _info = model.transcribe(
            audio,
            language="en",
            task="transcribe",
            beam_size=1,
            condition_on_previous_text=False,
            vad_filter=False,
            without_timestamps=True,
        )
        text = " ".join(segment.text.strip() for segment in segments).strip()
    return " ".join(text.split())
