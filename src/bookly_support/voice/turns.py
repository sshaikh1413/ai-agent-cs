"""When the customer starts, pauses, or talks over Mara.

Silero supplies the probability. This module only keeps the clock: about
half a second of silence ends a turn, and speech while Mara is audible
is a barge-in. One quiet frame does not throw that interrupt away.
When she stops, including the short tail after playback, audio already
captured over her stays with the customer.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

SAMPLE_RATE = 16_000
FRAME_SAMPLES = 512
FRAME_MS = 1000.0 * FRAME_SAMPLES / SAMPLE_RATE
# A little under Silero's usual 0.5, so a quiet mic still counts.
# Bleed that stays under this line does not open a turn.
SPEECH_THRESHOLD = 0.35
END_SILENCE_MS = 500.0
START_MS = 96.0
BARGE_MS = 160.0
PREROLL_MS = 192.0
MAX_UTTERANCE_MS = 20_000.0
MIN_UTTERANCE_MS = 300.0


@dataclass(frozen=True)
class ListenEvent:
    kind: str
    audio: np.ndarray | None = None


class TurnDetector:
    """16 kHz frames in. ``start``, ``end``, and ``barge`` out."""

    def __init__(self) -> None:
        self.mara_speaking = False
        self._preroll: list[np.ndarray] = []
        self._chunks: list[np.ndarray] = []
        self._barge_chunks: list[np.ndarray] = []
        self._voiced = False
        self._speech_ms = 0.0
        self._silence_ms = 0.0
        self._gap_ms = 0.0
        self._barge_ms = 0.0
        self._barge_gap_ms = 0.0
        self._pending = np.zeros(0, dtype=np.float32)

    def set_mara_speaking(self, speaking: bool) -> None:
        """Ignore a request to talk over a customer who already has the floor.

        Turning her off, including when the post-playback tail ends, keeps
        interrupt audio already captured and lets it be the customer's turn.
        """

        if speaking and self._voiced:
            return
        if speaking == self.mara_speaking:
            return
        self.mara_speaking = speaking
        if not speaking:
            self._adopt_interrupt()
            return
        self._barge_ms = 0.0
        self._barge_gap_ms = 0.0
        self._barge_chunks = []
        self._voiced = False
        self._speech_ms = 0.0
        self._silence_ms = 0.0
        self._gap_ms = 0.0
        self._chunks = []
        self._preroll = []

    def _adopt_interrupt(self) -> None:
        chunks = self._barge_chunks
        speech_ms = self._barge_ms
        self._barge_chunks = []
        self._barge_ms = 0.0
        self._barge_gap_ms = 0.0
        if not chunks:
            return
        self._chunks = list(chunks)
        self._preroll = []
        self._speech_ms = speech_ms
        self._silence_ms = 0.0
        self._gap_ms = 0.0
        if speech_ms >= START_MS:
            self._voiced = True

    def push_audio(self, samples: np.ndarray, probability) -> list[ListenEvent]:
        """Slice PCM into Silero frames. ``probability`` reads one frame."""

        if samples.size == 0:
            return []
        audio = np.concatenate([self._pending, np.asarray(samples, dtype=np.float32)])
        events: list[ListenEvent] = []
        offset = 0
        while offset + FRAME_SAMPLES <= len(audio):
            frame = audio[offset : offset + FRAME_SAMPLES]
            events.extend(self.push_frame(frame, float(probability(frame))))
            offset += FRAME_SAMPLES
        self._pending = audio[offset:]
        return events

    def push_frame(self, frame: np.ndarray, probability: float) -> list[ListenEvent]:
        events: list[ListenEvent] = []
        ms = 1000.0 * len(frame) / SAMPLE_RATE
        speech = probability >= SPEECH_THRESHOLD
        if self.mara_speaking:
            if speech:
                self._barge_gap_ms = 0.0
                self._barge_ms += ms
                self._barge_chunks.append(frame)
                if self._barge_ms >= BARGE_MS:
                    self._chunks = list(self._barge_chunks)
                    self._barge_chunks = []
                    self._barge_ms = 0.0
                    self._barge_gap_ms = 0.0
                    self._voiced = True
                    self._speech_ms = BARGE_MS
                    self._silence_ms = 0.0
                    self._gap_ms = 0.0
                    self.mara_speaking = False
                    events.append(ListenEvent("barge"))
            elif self._barge_chunks and self._barge_gap_ms + ms <= FRAME_MS:
                self._barge_gap_ms += ms
                self._barge_chunks.append(frame)
            else:
                self._barge_ms = 0.0
                self._barge_gap_ms = 0.0
                self._barge_chunks = []
            return events

        if speech:
            self._silence_ms = 0.0
            self._gap_ms = 0.0
            self._speech_ms += ms
            self._chunks.append(frame)
            if not self._voiced and self._speech_ms >= START_MS:
                self._voiced = True
                if self._preroll:
                    self._chunks = list(self._preroll) + self._chunks
                    self._preroll = []
                events.append(ListenEvent("start"))
            if self._voiced and self._utterance_ms() >= MAX_UTTERANCE_MS:
                events.append(ListenEvent("end", self._finish()))
        else:
            if self._voiced:
                self._chunks.append(frame)
                self._silence_ms += ms
                if self._silence_ms >= END_SILENCE_MS:
                    events.append(ListenEvent("end", self._finish()))
            elif self._chunks and self._gap_ms + ms <= FRAME_MS:
                self._gap_ms += ms
                self._chunks.append(frame)
            else:
                self._speech_ms = 0.0
                self._gap_ms = 0.0
                self._chunks = []
                self._preroll.append(frame)
                keep = max(1, int(PREROLL_MS / FRAME_MS))
                if len(self._preroll) > keep:
                    self._preroll = self._preroll[-keep:]
        return events

    def _utterance_ms(self) -> float:
        if not self._chunks:
            return 0.0
        samples = sum(len(chunk) for chunk in self._chunks)
        return 1000.0 * samples / SAMPLE_RATE

    def _finish(self) -> np.ndarray:
        audio = (
            np.concatenate(self._chunks)
            if self._chunks
            else np.zeros(0, dtype=np.float32)
        )
        self._chunks = []
        self._voiced = False
        self._speech_ms = 0.0
        self._silence_ms = 0.0
        self._gap_ms = 0.0
        return audio


def long_enough(audio: np.ndarray) -> bool:
    if audio.size == 0:
        return False
    return 1000.0 * audio.size / SAMPLE_RATE >= MIN_UTTERANCE_MS
