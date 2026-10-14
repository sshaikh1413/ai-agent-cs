"""Mara's voice. One sentence at a time, so a barge-in can cut the next one."""

from __future__ import annotations

import re
import threading
from collections.abc import Iterator

_lock = threading.Lock()
_voice = None
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def get_piper():
    global _voice
    if _voice is not None:
        return _voice
    with _lock:
        if _voice is None:
            from piper import PiperVoice

            from bookly_support.voice.models import piper_model_path

            _voice = PiperVoice.load(str(piper_model_path()))
        return _voice


def sentences(text: str) -> list[str]:
    parts = [part.strip() for part in _SENTENCE.split(text.strip())]
    kept = [part for part in parts if part]
    return kept or ([text.strip()] if text.strip() else [])


def iter_speech(text: str, cancel: threading.Event) -> Iterator[tuple[int, bytes]]:
    """PCM16 bytes and the voice sample rate. Stops when ``cancel`` is set."""

    spoken = text.strip()
    if not spoken:
        return
    voice = get_piper()
    with _lock:
        for sentence in sentences(spoken):
            if cancel.is_set():
                return
            for chunk in voice.synthesize(sentence):
                if cancel.is_set():
                    return
                yield chunk.sample_rate, bytes(chunk.audio_int16_bytes)
