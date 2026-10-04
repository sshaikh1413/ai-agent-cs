"""Local weights. They download on first use into the user cache, not the repo."""

from __future__ import annotations

import shutil
import threading
from pathlib import Path
from urllib.request import urlopen

CACHE = Path.home() / ".cache" / "bookly-voice"
SILERO_URL = (
    "https://github.com/snakers4/silero-vad/raw/v5.1.2/src/silero_vad/data/silero_vad.onnx"
)
PIPER_VOICE = "en_US-lessac-medium"
WHISPER_MODEL = "distil-small.en"

_lock = threading.Lock()
_ready = False


def silero_path() -> Path:
    return CACHE / "silero_vad.onnx"


def piper_dir() -> Path:
    return CACHE / "piper"


def piper_model_path() -> Path:
    return piper_dir() / f"{PIPER_VOICE}.onnx"


def whisper_dir() -> Path:
    return CACHE / "whisper"


def ensure_models() -> None:
    """Download Silero, Piper, and distil-small.en once. Safe to call again."""

    global _ready
    if _ready:
        return
    with _lock:
        if _ready:
            return
        _download(SILERO_URL, silero_path())
        _ensure_piper()
        _ensure_whisper()
        _ready = True


def _download(url: str, dest: Path) -> None:
    if dest.is_file() and dest.stat().st_size > 1000:
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_suffix(dest.suffix + ".part")
    with urlopen(url, timeout=120) as response, partial.open("wb") as handle:
        shutil.copyfileobj(response, handle)
    partial.replace(dest)


def _ensure_piper() -> None:
    model = piper_model_path()
    config = piper_dir() / f"{PIPER_VOICE}.onnx.json"
    if model.is_file() and model.stat().st_size > 1000 and config.is_file():
        return
    from piper.download_voices import download_voice

    piper_dir().mkdir(parents=True, exist_ok=True)
    download_voice(PIPER_VOICE, piper_dir())


def _ensure_whisper() -> None:
    """Constructing the model downloads ``distil-small.en`` into the cache."""

    from bookly_support.voice.stt import get_whisper

    get_whisper()
