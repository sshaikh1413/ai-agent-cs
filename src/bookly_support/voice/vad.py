"""Silero VAD on CPU, ONNX only. One instance per call, because the state is the call."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from bookly_support.voice.turns import FRAME_SAMPLES

# The v5.1.2 model reads 64 samples of context plus one 512-sample frame.
_CONTEXT = 64


class SileroVad:
    def __init__(self, model_path: Path) -> None:
        import onnxruntime

        options = onnxruntime.SessionOptions()
        options.inter_op_num_threads = 1
        options.intra_op_num_threads = 1
        self._session = onnxruntime.InferenceSession(
            str(model_path),
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )
        names = {item.name for item in self._session.get_inputs()}
        if not {"input", "state", "sr"} <= names:
            raise RuntimeError("This Silero file is not the v5 ONNX model.")
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._context = np.zeros((1, _CONTEXT), dtype=np.float32)
        self._sr = np.array(16_000, dtype=np.int64)

    def __call__(self, frame: np.ndarray) -> float:
        chunk = np.asarray(frame, dtype=np.float32).reshape(1, -1)
        if chunk.shape[1] != FRAME_SAMPLES:
            raise ValueError(f"Silero expects {FRAME_SAMPLES} samples at 16 kHz.")
        audio = np.concatenate([self._context, chunk], axis=1)
        output, state = self._session.run(
            None,
            {"input": audio, "state": self._state, "sr": self._sr},
        )
        self._state = state
        self._context = audio[:, -_CONTEXT:]
        return float(np.asarray(output).reshape(-1)[0])
