"""
Transcribe audio using faster-whisper (local, no API).
Returns segments with word-level timestamps for precise sync.
"""
import asyncio
from pathlib import Path
from typing import Generator

from faster_whisper import WhisperModel

from backend.config import WHISPER_MODEL, WHISPER_COMPUTE_TYPE

_model: WhisperModel | None = None


def _get_model() -> WhisperModel:
    global _model
    if _model is None:
        _model = WhisperModel(WHISPER_MODEL, compute_type=WHISPER_COMPUTE_TYPE)
    return _model


async def transcribe(audio_path: Path, language: str | None = None) -> list[dict]:
    """
    Transcribe audio file and return segments with timestamps.

    Returns list of:
        {
            "start": float,   # segment start time in seconds
            "end": float,     # segment end time in seconds
            "text": str,      # transcribed text
        }
    """
    loop = asyncio.get_event_loop()

    def _run():
        model = _get_model()
        segments, info = model.transcribe(
            str(audio_path),
            language=language,
            word_timestamps=True,
            vad_filter=True,          # skip silence
            vad_parameters={"min_silence_duration_ms": 500},
        )

        result = []
        for seg in segments:
            result.append({
                "start": seg.start,
                "end": seg.end,
                "text": seg.text.strip(),
            })
        return result

    return await loop.run_in_executor(None, _run)


async def detect_language(audio_path: Path) -> str:
    """Detect the spoken language in the first 30 seconds of audio."""
    loop = asyncio.get_event_loop()

    def _run():
        model = _get_model()
        _, info = model.transcribe(str(audio_path), language=None)
        return info.language

    return await loop.run_in_executor(None, _run)
