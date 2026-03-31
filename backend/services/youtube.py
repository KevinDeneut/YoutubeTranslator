"""
Download audio and video from YouTube using yt-dlp.
"""
import asyncio
from pathlib import Path
import yt_dlp


async def get_video_info(url: str) -> dict:
    """Fetch video metadata without downloading."""
    opts = {"quiet": True, "no_warnings": True}
    loop = asyncio.get_event_loop()

    def _fetch():
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=False)

    info = await loop.run_in_executor(None, _fetch)
    return {
        "title": info.get("title"),
        "duration": info.get("duration"),
        "channel": info.get("uploader"),
        "thumbnail": info.get("thumbnail"),
        "id": info.get("id"),
    }


async def download_audio(url: str, output_path: Path, progress_cb=None) -> Path:
    """
    Download audio from a YouTube video as a WAV file.
    Returns the path to the downloaded file.
    """
    output_template = str(output_path / "%(id)s.%(ext)s")

    def _progress_hook(d):
        if progress_cb and d["status"] == "downloading":
            pct = d.get("_percent_str", "?").strip()
            progress_cb(f"Downloading audio: {pct}")

    opts = {
        "format": "bestaudio/best",
        "outtmpl": output_template,
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [_progress_hook],
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "wav",
                "preferredquality": "192",
            }
        ],
    }

    loop = asyncio.get_event_loop()

    def _download():
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            video_id = info.get("id")
            return output_path / f"{video_id}.wav"

    return await loop.run_in_executor(None, _download)


async def download_video(url: str, output_path: Path, progress_cb=None) -> Path:
    """
    Download video (no audio) as MP4 for later merging.
    Returns the path to the video file.
    """
    output_template = str(output_path / "%(id)s_video.%(ext)s")

    def _progress_hook(d):
        if progress_cb and d["status"] == "downloading":
            pct = d.get("_percent_str", "?").strip()
            progress_cb(f"Downloading video: {pct}")

    opts = {
        # Download video-only stream
        "format": "bestvideo[ext=mp4]/bestvideo",
        "outtmpl": output_template,
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [_progress_hook],
    }

    loop = asyncio.get_event_loop()

    def _download():
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            video_id = info.get("id")
            # yt-dlp may choose a different extension
            candidates = list(output_path.glob(f"{video_id}_video.*"))
            if not candidates:
                raise FileNotFoundError(f"Video download failed for {video_id}")
            return candidates[0]

    return await loop.run_in_executor(None, _download)


async def extract_clip(audio_path: Path, start: float, duration: float, out_path: Path) -> Path:
    """Cut a clip from an audio file using ffmpeg (for voice profile extraction)."""
    import ffmpeg

    loop = asyncio.get_event_loop()

    def _cut():
        (
            ffmpeg
            .input(str(audio_path), ss=start, t=duration)
            .output(str(out_path), ar=22050, ac=1)
            .overwrite_output()
            .run(quiet=True)
        )
        return out_path

    return await loop.run_in_executor(None, _cut)
