"""Detección de voz en tiempo real con Silero VAD (el modelo ONNX que trae faster-whisper)."""
import os

import numpy as np

SAMPLE_RATE = 16000
FRAME = 512                 # 32 ms a 16 kHz
CONTEXT = 64
FRAME_MS = FRAME * 1000 / SAMPLE_RATE

_session = None


def _get_session():
    global _session
    if _session is None:
        import onnxruntime
        from faster_whisper.utils import get_assets_path

        opts = onnxruntime.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        opts.log_severity_level = 4
        _session = onnxruntime.InferenceSession(os.path.join(get_assets_path(), "silero_vad_v6.onnx"),
                                                providers=["CPUExecutionProvider"], sess_options=opts)
    return _session


class StreamingVAD:
    """Probabilidad de voz por trama de 32 ms, conservando el estado entre tramas."""

    def __init__(self):
        self.session = _get_session()
        self.reset()

    def reset(self):
        self.h = np.zeros((1, 1, 128), dtype=np.float32)
        self.c = np.zeros((1, 1, 128), dtype=np.float32)
        self.context = np.zeros(CONTEXT, dtype=np.float32)

    def prob(self, frame: np.ndarray) -> float:
        x = np.concatenate([self.context, frame]).astype(np.float32)[None, :]
        out, self.h, self.c = self.session.run(None, {"input": x, "h": self.h, "c": self.c})
        self.context = frame[-CONTEXT:]
        return float(np.asarray(out).reshape(-1)[-1])
