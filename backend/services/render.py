"""
Merge synthesized audio segments with the original video using ffmpeg.
Handles timing alignment: stretches/compresses synthesized audio to fit
the original segment duration (within ±40% to preserve naturalness).
"""
import asyncio
from pathlib import Path

import ffmpeg
from pydub import AudioSegment

MAX_SPEED_FACTOR = 1.4   # max 40% faster
MIN_SPEED_FACTOR = 0.75  # max 25% slower


def _get_audio_duration(path: Path) -> float:
    """Get duration of an audio file in seconds."""
    probe = ffmpeg.probe(str(path))
    stream = next(s for s in probe["streams"] if s["codec_type"] == "audio")
    return float(stream["duration"])


def _adjust_audio_speed(input_path: Path, output_path: Path, speed: float) -> None:
    """
    Adjust playback speed of an audio file using ffmpeg atempo filter.
    atempo supports 0.5–2.0; chain filters for values outside this range.
    """
    # atempo is limited to [0.5, 2.0] per filter; chain if needed
    filters = []
    remaining = speed
    while remaining > 2.0:
        filters.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5:
        filters.append("atempo=0.5")
        remaining /= 0.5
    filters.append(f"atempo={remaining:.4f}")
    filter_str = ",".join(filters)

    (
        ffmpeg
        .input(str(input_path))
        .filter("atempo", remaining)  # simplified; use complex filter below
        .output(str(output_path))
        .overwrite_output()
        .run(quiet=True)
    )


def _adjust_speed_pydub(input_path: Path, output_path: Path, speed: float) -> None:
    """Adjust speed via pydub (frame rate trick — fast and no quality loss)."""
    audio = AudioSegment.from_wav(str(input_path))
    # Change frame rate = change speed without pitch shift
    new_frame_rate = int(audio.frame_rate * speed)
    sped = audio._spawn(audio.raw_data, overrides={"frame_rate": new_frame_rate})
    sped = sped.set_frame_rate(audio.frame_rate)
    sped.export(str(output_path), format="wav")


async def build_audio_track(
    segments: list[dict],
    original_duration: float,
    output_path: Path,
    progress_cb=None,
) -> Path:
    """
    Build a full audio track from synthesized segments, aligned to original timing.

    Strategy:
    - For each segment, place synthesized audio at the original start time.
    - If synthesized audio is longer than the slot, speed it up (cap at MAX_SPEED_FACTOR).
    - If it's shorter, add silence padding to fill the gap.
    """
    loop = asyncio.get_event_loop()

    def _build():
        sample_rate = 22050
        total_ms = int(original_duration * 1000) + 500
        track = AudioSegment.silent(duration=total_ms, frame_rate=sample_rate)

        for i, seg in enumerate(segments):
            audio_path = seg.get("audio_path")
            if not audio_path or not Path(audio_path).exists():
                continue

            start_ms = int(seg["start"] * 1000)
            slot_ms = int((seg["end"] - seg["start"]) * 1000)

            synth = AudioSegment.from_wav(audio_path)
            synth_ms = len(synth)

            if slot_ms > 0 and synth_ms > 0:
                speed = synth_ms / slot_ms
                speed = max(MIN_SPEED_FACTOR, min(MAX_SPEED_FACTOR, speed))

                if abs(speed - 1.0) > 0.05:
                    adjusted_path = Path(audio_path).with_suffix(".adj.wav")
                    _adjust_speed_pydub(Path(audio_path), adjusted_path, speed)
                    synth = AudioSegment.from_wav(str(adjusted_path))

            # Overlay at the correct timestamp
            track = track.overlay(synth, position=start_ms)

            if progress_cb:
                progress_cb(f"Building audio track: {i + 1}/{len(segments)}")

        track.export(str(output_path), format="wav")
        return output_path

    return await loop.run_in_executor(None, _build)


async def merge_video_audio(
    video_path: Path,
    audio_path: Path,
    output_path: Path,
    progress_cb=None,
) -> Path:
    """Merge video with the new audio track, replacing original audio."""
    if progress_cb:
        progress_cb("Merging video and audio...")

    loop = asyncio.get_event_loop()

    def _merge():
        video = ffmpeg.input(str(video_path))
        audio = ffmpeg.input(str(audio_path))
        (
            ffmpeg
            .output(
                video.video,
                audio.audio,
                str(output_path),
                vcodec="copy",
                acodec="aac",
                audio_bitrate="192k",
                shortest=None,
            )
            .overwrite_output()
            .run(quiet=True)
        )
        return output_path

    return await loop.run_in_executor(None, _merge)
