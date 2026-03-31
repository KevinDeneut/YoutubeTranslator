"""
Voice cloning and TTS synthesis using Coqui XTTS v2 (local, no API).
First run downloads the model (~1.8 GB) automatically.
"""
import asyncio
import json
from pathlib import Path

from backend.config import PROFILES_DIR, XTTS_MODEL, XTTS_LANGUAGES

_tts = None


def _get_tts():
    global _tts
    if _tts is None:
        import os
        os.environ["COQUI_TOS_AGREED"] = "1"  # auto-accept non-commercial license
        from TTS.api import TTS
        print("[voice] Loading XTTS v2 model (first run may download ~1.8 GB)...")
        _tts = TTS(XTTS_MODEL)
    return _tts


def save_voice_profile(profile_id: str, reference_audio: Path, metadata: dict) -> Path:
    """
    Save a voice profile: copy the reference audio and store metadata.
    The reference audio is what XTTS uses for voice cloning.
    """
    profile_dir = PROFILES_DIR / profile_id
    profile_dir.mkdir(parents=True, exist_ok=True)

    # Copy reference audio
    import shutil
    ref_dest = profile_dir / "reference.wav"
    shutil.copy2(reference_audio, ref_dest)

    # Save metadata
    meta_path = profile_dir / "metadata.json"
    meta_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2))

    return profile_dir


def load_voice_profiles() -> list[dict]:
    """Return all saved voice profiles."""
    profiles = []
    for profile_dir in PROFILES_DIR.iterdir():
        if not profile_dir.is_dir():
            continue
        meta_path = profile_dir / "metadata.json"
        if meta_path.exists():
            meta = json.loads(meta_path.read_text())
            meta["id"] = profile_dir.name
            meta["reference_audio"] = str(profile_dir / "reference.wav")
            profiles.append(meta)
    return profiles


def get_voice_profile(profile_id: str) -> dict | None:
    """Get a single voice profile by ID."""
    profile_dir = PROFILES_DIR / profile_id
    meta_path = profile_dir / "metadata.json"
    if not meta_path.exists():
        return None
    meta = json.loads(meta_path.read_text())
    meta["id"] = profile_id
    meta["reference_audio"] = str(profile_dir / "reference.wav")
    return meta


async def synthesize_segment(
    text: str,
    target_language: str,
    reference_audio: Path,
    output_path: Path,
) -> Path:
    """
    Synthesize speech for a single text segment using XTTS v2 voice cloning.
    The reference_audio is used to clone the voice characteristics.
    Returns the output audio file path.
    """
    xtts_lang = XTTS_LANGUAGES.get(target_language, "en")
    loop = asyncio.get_event_loop()

    def _run():
        tts = _get_tts()
        tts.tts_to_file(
            text=text,
            speaker_wav=str(reference_audio),
            language=xtts_lang,
            file_path=str(output_path),
        )
        return output_path

    return await loop.run_in_executor(None, _run)


async def synthesize_all_segments(
    segments: list[dict],
    target_language: str,
    reference_audio: Path,
    output_dir: Path,
    progress_cb=None,
) -> list[dict]:
    """
    Synthesize all translated segments sequentially.
    Returns segments with "audio_path" and "synthesis_time_s" added.
    """
    import time as _time
    output_dir.mkdir(parents=True, exist_ok=True)
    result = []
    total = len(segments)

    for i, seg in enumerate(segments):
        text = seg.get("translated_text", seg["text"])
        if not text.strip():
            result.append({**seg, "audio_path": None, "synthesis_time_s": 0.0})
            continue

        out_file = output_dir / f"seg_{i:04d}.wav"
        t0 = _time.time()
        await synthesize_segment(text, target_language, reference_audio, out_file)
        elapsed = round(_time.time() - t0, 2)

        result.append({**seg, "audio_path": str(out_file), "synthesis_time_s": elapsed})

        if progress_cb:
            seg_start = seg.get("start", 0)
            pct = round((i + 1) / total * 100)
            progress_cb(
                f"Synthesizing voice: segment {i + 1}/{total} ({pct}%)"
                f" -- {int(seg_start // 60)}:{int(seg_start % 60):02d} in video"
                f" [{elapsed}s/seg]"
            )

    return result
