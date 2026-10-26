"""Local Portuguese speech transcription without retaining the audio."""

import io
from functools import lru_cache
from pathlib import Path


class AudioTooLong(ValueError):
    pass


@lru_cache(maxsize=1)
def _model():
    from faster_whisper import WhisperModel

    directory = Path(__file__).resolve().parent.parent / ".tmp" / "transcription-models"
    return WhisperModel("small", device="cpu", compute_type="int8", cpu_threads=4,
                        download_root=str(directory), local_files_only=True)


def transcribe_local(data: bytes) -> str:
    # shortcut: one five-minute CPU job at a time; use a worker queue for longer recordings.
    segments, info = _model().transcribe(io.BytesIO(data), language="pt", beam_size=3,
                                         vad_filter=True, condition_on_previous_text=False)
    if info.duration > 300:
        raise AudioTooLong("O áudio deve ter até 5 minutos.")
    return " ".join(segment.text.strip() for segment in segments).strip()
