"""
Voice cloning and TTS synthesis using Coqui XTTS v2 (local, no API).
First run downloads the model (~1.8 GB) automatically.

v2 optimisations:
  - Speaker embedding caching: conditioning latents computed once per job (~20-40% faster)
  - Segment merging: adjacent segments merged up to MAX_SEGMENT_DURATION to reduce TTS calls (~30-50% faster)
"""
import asyncio
import json
from pathlib import Path

import numpy as np
import soundfile as sf

from backend.config import PROFILES_DIR, XTTS_MODEL, XTTS_LANGUAGES

MAX_SEGMENT_DURATION = 15.0  # seconds — merge segments up to this combined length

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


# ─── Voice profiles ────────────────────────────────────────────────────────────

def save_voice_profile(profile_id: str, reference_audio: Path, metadata: dict) -> Path:
    """
    Save a voice profile: copy the reference audio and store metadata.
    The reference audio is what XTTS uses for voice cloning.
    """
    profile_dir = PROFILES_DIR / profile_id
    profile_dir.mkdir(parents=True, exist_ok=True)

    import shutil
    ref_dest = profile_dir / "reference.wav"
    shutil.copy2(reference_audio, ref_dest)

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


# ─── Speaker embedding cache ───────────────────────────────────────────────────

def _compute_speaker_latents(reference_audio: Path):
    """
    Compute XTTS v2 conditioning latents from reference audio.
    Call once per job; reuse for every segment to avoid redundant computation.
    """
    tts = _get_tts()
    model = tts.synthesizer.tts_model
    gpt_cond_latent, speaker_embedding = model.get_conditioning_latents(
        audio_path=[str(reference_audio)]
    )
    return gpt_cond_latent, speaker_embedding


def _run_inference(text: str, xtts_lang: str, gpt_cond_latent, speaker_embedding, output_path: Path) -> Path:
    """Run XTTS inference synchronously using precomputed speaker latents."""
    tts = _get_tts()
    model = tts.synthesizer.tts_model

    out = model.inference(
        text=text,
        language=xtts_lang,
        gpt_cond_latent=gpt_cond_latent,
        speaker_embedding=speaker_embedding,
    )
    wav = out["wav"]
    if hasattr(wav, "cpu"):
        wav = wav.cpu().numpy()

    sample_rate = model.config.audio.output_sample_rate  # 24000 for XTTS v2
    sf.write(str(output_path), wav, sample_rate)
    return output_path


# ─── Segment merging ───────────────────────────────────────────────────────────

def _merge_buffer(buffer: list[dict]) -> dict:
    """Collapse a buffer of segments into one merged segment (used by the pipeline)."""
    if len(buffer) == 1:
        return buffer[0]
    merged = dict(buffer[0])
    for seg in buffer[1:]:
        for key in ("translated_text", "text"):
            if key in merged or key in seg:
                merged[key] = (
                    (merged.get(key) or "").rstrip() + " " + (seg.get(key) or "").lstrip()
                ).strip()
        merged["end"] = seg["end"]
    merged["_sub_count"] = len(buffer)
    return merged



def merge_segments(segments: list[dict], max_duration: float = MAX_SEGMENT_DURATION) -> list[dict]:
    """
    Merge adjacent segments into chunks up to max_duration seconds.
    Reduces the number of TTS calls significantly for short segments.
    The merged segment keeps start of first + end of last sub-segment.
    """
    if not segments:
        return segments

    merged = []
    current: dict | None = None

    for seg in segments:
        if current is None:
            current = dict(seg)
            current["_sub_count"] = 1
            continue

        if seg["end"] - current["start"] <= max_duration:
            # Merge into current
            for key in ("translated_text", "text"):
                if key in current or key in seg:
                    current[key] = (current.get(key) or "").rstrip() + " " + (seg.get(key) or "").lstrip()
            current["end"] = seg["end"]
            current["_sub_count"] += 1
        else:
            merged.append(current)
            current = dict(seg)
            current["_sub_count"] = 1

    if current:
        merged.append(current)

    return merged


# ─── Synthesis ─────────────────────────────────────────────────────────────────

async def synthesize_segment(
    text: str,
    target_language: str,
    reference_audio: Path,
    output_path: Path,
) -> Path:
    """
    Synthesize a single segment using the old per-call approach (kept for compatibility).
    Used by the voice-profile creation job which only needs one clip.
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
    v2: merge segments + cache speaker latents, then synthesize each merged chunk.
    Returns segments list (merged) with audio_path and synthesis_time_s added.
    """
    import time as _time
    output_dir.mkdir(parents=True, exist_ok=True)
    xtts_lang = XTTS_LANGUAGES.get(target_language, "en")
    loop = asyncio.get_event_loop()

    # Step 1 — merge short segments
    original_count = len(segments)
    segments = merge_segments(segments)
    merged_count = len(segments)

    if progress_cb:
        progress_cb(
            f"Merged {original_count} segments → {merged_count} chunks"
            f" (saved {original_count - merged_count} TTS calls)"
        )

    # Step 2 — compute speaker latents once
    if progress_cb:
        progress_cb("Computing speaker embedding...")

    gpt_cond_latent, speaker_embedding = await loop.run_in_executor(
        None, _compute_speaker_latents, reference_audio
    )

    # Step 3 — synthesize each merged chunk
    result = []
    total = len(segments)

    for i, seg in enumerate(segments):
        text = (seg.get("translated_text") or seg.get("text") or "").strip()
        if not text:
            result.append({**seg, "audio_path": None, "synthesis_time_s": 0.0})
            continue

        out_file = output_dir / f"seg_{i:04d}.wav"
        t0 = _time.time()

        await loop.run_in_executor(
            None, _run_inference, text, xtts_lang, gpt_cond_latent, speaker_embedding, out_file
        )

        elapsed = round(_time.time() - t0, 2)
        result.append({**seg, "audio_path": str(out_file), "synthesis_time_s": elapsed})

        if progress_cb:
            seg_start = seg.get("start", 0)
            pct = round((i + 1) / total * 100)
            progress_cb(
                f"Synthesizing voice: chunk {i + 1}/{total} ({pct}%)"
                f" -- {int(seg_start // 60)}:{int(seg_start % 60):02d} in video"
                f" [{elapsed}s/chunk]"
            )

    return result
