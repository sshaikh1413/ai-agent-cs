"""WebSocket call. Mic PCM in, checker-accepted speech out. The desk is unchanged."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from collections.abc import Callable

import numpy as np
from fastapi import WebSocket, WebSocketDisconnect

from bookly_support.agent.provider import ChatRequest
from bookly_support.config import ALLOWED_CUSTOMER_IDS, CUSTOMER_ID
from bookly_support.voice.desk import CALL_GREETING, answer_transcript, reply_payload
from bookly_support.voice.turns import TurnDetector, long_enough

log = logging.getLogger(__name__)

_VOICE_ERROR = "Mara's voice didn't load. You can keep typing."
_DESK_ERROR = "Mara's desk didn't answer. Nothing was filed. You can keep typing."


class Speaker:
    """Piper on a side thread. A newer generation drops audio that is already queued."""

    def __init__(self, enqueue: Callable[[tuple], None]) -> None:
        self._enqueue = enqueue
        self.cancel = threading.Event()
        self.generation = 0
        self.playing = False
        self.tail_until = 0.0
        self._thread: threading.Thread | None = None

    def audible(self) -> bool:
        return self.playing or _now() < self.tail_until

    def stop(self, notify: bool = True) -> None:
        audible = self.audible()
        self.cancel.set()
        self.playing = False
        self.tail_until = 0.0
        self.generation += 1
        if notify and audible:
            self._enqueue(("json", {"type": "barge_in"}))

    def start(self, text: str) -> None:
        self.stop(notify=self.playing)
        generation = self.generation
        cancel = threading.Event()
        self.cancel = cancel
        self.playing = True

        def run() -> None:
            started = False
            try:
                from bookly_support.voice.models import ensure_models
                from bookly_support.voice.tts import iter_speech

                ensure_models()
                for sample_rate, pcm in iter_speech(text, cancel):
                    if cancel.is_set() or generation != self.generation:
                        break
                    if not started:
                        self._enqueue(
                            (
                                "json",
                                {"type": "audio_start", "sample_rate": sample_rate},
                                generation,
                            )
                        )
                        started = True
                    self._enqueue(("bytes", pcm, generation))
            except Exception as exc:
                log.warning("Mara's voice failed: %s", type(exc).__name__)
                self._enqueue(("json", {"type": "error", "message": _VOICE_ERROR}))
            finally:
                if generation == self.generation:
                    self.playing = False
                    self.tail_until = _now() + 0.35
                    if started:
                        self._enqueue(("json", {"type": "audio_end"}, generation))

        self._thread = threading.Thread(target=run, name="mara-voice", daemon=True)
        self._thread.start()


def _now() -> float:
    import time

    return time.monotonic()


def pcm16_to_float(data: bytes) -> np.ndarray:
    if len(data) % 2:
        data = data[: len(data) - 1]
    if not data:
        return np.zeros(0, dtype=np.float32)
    return np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768.0


def _customer(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        return CUSTOMER_ID
    cleaned = value.strip()
    if cleaned not in ALLOWED_CUSTOMER_IDS:
        raise ValueError(cleaned)
    return cleaned


async def handle_voice(websocket: WebSocket, agent_factory: Callable[[], object]) -> None:
    await websocket.accept()
    outgoing: asyncio.Queue = asyncio.Queue()
    incoming: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def enqueue(item: tuple) -> None:
        loop.call_soon_threadsafe(outgoing.put_nowait, item)

    speaker = Speaker(enqueue)

    async def writer() -> None:
        while True:
            item = await outgoing.get()
            if item is None:
                return
            kind = item[0]
            generation = item[2] if len(item) > 2 else None
            if generation is not None and generation != speaker.generation:
                continue
            if kind == "json":
                await websocket.send_json(item[1])
            elif kind == "bytes":
                await websocket.send_bytes(item[1])

    async def reader() -> None:
        try:
            while True:
                await incoming.put(await websocket.receive())
        except WebSocketDisconnect:
            await incoming.put({"type": "websocket.disconnect"})
        except Exception:
            await incoming.put({"type": "websocket.disconnect"})

    writer_task = asyncio.create_task(writer())
    reader_task = asyncio.create_task(reader())
    try:
        first = await incoming.get()
        if not isinstance(first, dict) or first.get("type") == "websocket.disconnect":
            return
        start = _json_message(first)
        if start is None or start.get("type") != "start":
            try:
                await websocket.close(code=1008)
            except Exception:
                return
            return
        try:
            customer_id = _customer(start.get("customer_id"))
        except ValueError:
            enqueue(("json", {"type": "error", "message": "That account isn't on this desk."}))
            return

        conversation_id = _conversation(start.get("conversation_id"))
        last_status = ""

        def status(state: str) -> None:
            nonlocal last_status
            if state == last_status:
                return
            last_status = state
            enqueue(("json", {"type": "status", "state": state}))

        enqueue(("json", {"type": "greeting", "text": CALL_GREETING}))
        status("starting")
        speaker.start(CALL_GREETING)

        detector = TurnDetector()
        vad = None
        working = False
        queued: str | None = None

        async def submit(text: str) -> None:
            nonlocal working, queued, conversation_id
            cleaned = " ".join(text.split())
            if not cleaned:
                return
            if working:
                queued = cleaned
                speaker.stop(notify=True)
                return
            working = True
            try:
                enqueue(("json", {"type": "transcript", "role": "user", "text": cleaned}))
                status("thinking")
                request = ChatRequest(
                    message=cleaned,
                    history=[],
                    conversation_id=conversation_id,
                    customer_id=customer_id,
                )
                try:
                    reply = await asyncio.to_thread(answer_transcript, agent_factory(), request)
                except Exception as exc:
                    log.warning("Voice desk failed: %s", type(exc).__name__)
                    enqueue(("json", {"type": "error", "message": _DESK_ERROR}))
                    status("listening")
                    return
                conversation_id = reply.conversation_id
                payload = reply_payload(reply)
                enqueue(("json", payload))
                if queued:
                    status("thinking")
                    return
                status("speaking")
                detector.set_mara_speaking(True)
                speaker.start(payload["spoken"])
            finally:
                working = False
            if queued:
                nxt = queued
                queued = None
                await submit(nxt)

        while True:
            message = await incoming.get()
            if message is None or message.get("type") == "websocket.disconnect":
                break
            data = _json_message(message)
            if data is not None:
                kind = data.get("type")
                if kind == "stop":
                    break
                if kind == "text" and isinstance(data.get("text"), str):
                    await submit(data["text"])
                continue
            raw = message.get("bytes")
            if not raw:
                continue
            if vad is None:
                try:
                    from bookly_support.voice.models import ensure_models, silero_path
                    from bookly_support.voice.vad import SileroVad

                    await asyncio.to_thread(ensure_models)
                    vad = SileroVad(silero_path())
                except Exception as exc:
                    log.warning("Voice models failed: %s", type(exc).__name__)
                    enqueue(("json", {"type": "error", "message": _VOICE_ERROR}))
                    continue
            detector.set_mara_speaking(speaker.audible())
            samples = pcm16_to_float(raw)
            for event in detector.push_audio(samples, vad):
                if event.kind == "barge":
                    speaker.stop(notify=True)
                    detector.set_mara_speaking(False)
                    status("listening")
                elif event.kind == "end" and event.audio is not None and long_enough(event.audio):
                    try:
                        from bookly_support.voice.stt import transcribe

                        transcript = await asyncio.to_thread(transcribe, event.audio)
                    except Exception as exc:
                        log.warning("Transcription failed: %s", type(exc).__name__)
                        enqueue(("json", {"type": "error", "message": _VOICE_ERROR}))
                        continue
                    if transcript:
                        await submit(transcript)
            if not speaker.audible() and not working:
                status("listening")
    finally:
        speaker.stop(notify=False)
        reader_task.cancel()
        await outgoing.put(None)
        try:
            await writer_task
        except Exception:
            pass
        try:
            await reader_task
        except (asyncio.CancelledError, Exception):
            pass


def _conversation(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _json_message(message: object) -> dict | None:
    if not isinstance(message, dict):
        return None
    text = message.get("text")
    if not isinstance(text, str) or not text:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(data, dict):
        return data
    return None
