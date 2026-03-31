"""
YoutubeTranslator — FastAPI backend
"""
import asyncio
import json
import logging
import shutil
import time
import traceback
import uuid
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("yt-translator")

from fastapi import FastAPI, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.config import (
    APP_VERSION,
    BASE_DIR,
    JOBS_DIR,
    PROFILES_DIR,
    SUPPORTED_LANGUAGES,
    TEMP_DIR,
)
from backend.jobs import JobStatus, create_job, delete_job, get_job, list_jobs
from backend.services import voice, youtube
from backend.services.transcribe import detect_language, transcribe
from backend.services.translate import translate_segments
from backend.services.render import build_audio_track, merge_video_audio

app = FastAPI(title="YoutubeTranslator", version="0.1.0")


def _make_progress_cb(job):
    """
    Thread-safe progress callback: only updates the attribute.
    Broadcasting is handled by the WebSocket ping loop.
    """
    def cb(message: str):
        job.progress = message   # GIL makes simple str assignment thread-safe in CPython
    return cb

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve the frontend
frontend_dir = BASE_DIR / "frontend"
if frontend_dir.exists():
    app.mount("/app", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")

# Serve generated output files
data_dir = BASE_DIR / "data"
app.mount("/data", StaticFiles(directory=str(data_dir)), name="data")


# ─── Models ───────────────────────────────────────────────────────────────────

class VideoInfoRequest(BaseModel):
    url: str

class VoiceProfileRequest(BaseModel):
    name: str
    youtube_url: str
    start_time: float = 30.0
    duration: float = 20.0

class TranslateRequest(BaseModel):
    youtube_url: str
    source_language: str | None = None
    target_language: str
    voice_profile_id: str


# ─── Info endpoints ────────────────────────────────────────────────────────────

@app.get("/api/languages")
def get_languages():
    return SUPPORTED_LANGUAGES

@app.post("/api/video-info")
async def get_video_info(req: VideoInfoRequest):
    try:
        info = await youtube.get_video_info(req.url)
        return info
    except Exception as e:
        raise HTTPException(400, str(e))


# ─── Voice profiles ────────────────────────────────────────────────────────────

@app.get("/api/voice-profiles")
def get_voice_profiles():
    return voice.load_voice_profiles()

@app.get("/api/voice-profiles/{profile_id}")
def get_voice_profile(profile_id: str):
    profile = voice.get_voice_profile(profile_id)
    if not profile:
        raise HTTPException(404, "Profile not found")
    return profile

@app.delete("/api/voice-profiles/{profile_id}")
def delete_voice_profile(profile_id: str):
    profile_dir = PROFILES_DIR / profile_id
    if not profile_dir.exists():
        raise HTTPException(404, "Profile not found")
    shutil.rmtree(profile_dir)
    return {"ok": True}

@app.post("/api/voice-profiles")
async def create_voice_profile(req: VoiceProfileRequest):
    job = create_job(f"Voice profile: {req.name}")

    async def _run():
        progress = _make_progress_cb(job)
        temp_dir = TEMP_DIR / job.id
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            await job.update("Downloading audio...", JobStatus.RUNNING)
            audio_path = await youtube.download_audio(
                req.youtube_url, temp_dir, progress_cb=progress
            )

            await job.update("Extracting voice clip...")
            clip_path = temp_dir / "reference_clip.wav"
            await youtube.extract_clip(audio_path, req.start_time, req.duration, clip_path)

            await job.update("Saving voice profile...")
            profile_id = str(uuid.uuid4())[:8]
            video_info = await youtube.get_video_info(req.youtube_url)
            voice.save_voice_profile(
                profile_id,
                clip_path,
                {
                    "name": req.name,
                    "source_url": req.youtube_url,
                    "channel": video_info.get("channel", ""),
                    "start_time": req.start_time,
                    "duration": req.duration,
                },
            )

            await job.finish({
                "profile_id": profile_id,
                "name": req.name,
                "reference_audio_url": f"/data/voice_profiles/{profile_id}/reference.wav",
            })
        except Exception as e:
            tb = traceback.format_exc()
            log.error("Job %s failed:\n%s", job.id, tb)
            await job.fail(f"{e}\n\n{tb}")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    asyncio.create_task(_run())
    return {"job_id": job.id}


@app.post("/api/voice-profiles/upload")
async def upload_voice_profile(name: str, file: UploadFile):
    temp_path = TEMP_DIR / f"{uuid.uuid4()}.wav"
    with open(temp_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    profile_id = str(uuid.uuid4())[:8]
    voice.save_voice_profile(
        profile_id,
        temp_path,
        {"name": name, "source_url": "uploaded", "channel": ""},
    )
    temp_path.unlink(missing_ok=True)

    return {
        "profile_id": profile_id,
        "name": name,
        "reference_audio_url": f"/data/voice_profiles/{profile_id}/reference.wav",
    }


# ─── Translation jobs ──────────────────────────────────────────────────────────

@app.post("/api/translate")
async def translate_video(req: TranslateRequest):
    profile = voice.get_voice_profile(req.voice_profile_id)
    if not profile:
        raise HTTPException(404, "Voice profile not found")

    target_name = SUPPORTED_LANGUAGES.get(req.target_language, req.target_language)
    job = create_job(f"Translate to {target_name}")

    async def _run():
        progress = _make_progress_cb(job)
        job_dir = JOBS_DIR / job.id
        job_dir.mkdir(parents=True, exist_ok=True)
        temp_dir = TEMP_DIR / job.id
        temp_dir.mkdir(parents=True, exist_ok=True)

        timing: dict = {}
        t_start = time.time()

        # Initialize metadata early so partial info is saved on each update
        job.metadata.update({
            "version": APP_VERSION,
            "target_language": req.target_language,
            "source_language": req.source_language,
            "voice_profile": {"id": req.voice_profile_id, "name": profile["name"]},
            "timing": timing,
        })

        try:
            # 1. Video info
            await job.update("Fetching video info...", JobStatus.RUNNING)
            video_info = await youtube.get_video_info(req.youtube_url)
            job.metadata["video"] = {
                "title": video_info.get("title", ""),
                "channel": video_info.get("channel", ""),
                "duration": video_info.get("duration", 0),
                "url": req.youtube_url,
            }

            # 2. Download audio + video in parallel
            timing["download_start"] = time.time()
            await job.update("Downloading...")
            t0 = timing["download_start"]
            audio_task = asyncio.create_task(
                youtube.download_audio(req.youtube_url, temp_dir, progress_cb=progress)
            )
            video_task = asyncio.create_task(
                youtube.download_video(req.youtube_url, job_dir, progress_cb=progress)
            )
            audio_path, video_path = await asyncio.gather(audio_task, video_task)
            timing["download_s"] = round(time.time() - t0, 1)
            await job.update(f"Downloaded ({timing['download_s']}s)")

            # 3. Transcribe
            timing["transcribe_start"] = time.time()
            await job.update("Transcribing audio...")
            t0 = timing["transcribe_start"]
            source_lang = req.source_language
            if not source_lang:
                source_lang = await detect_language(audio_path)
                await job.update(f"Detected language: {source_lang}")
            job.metadata["source_language"] = source_lang

            segments = await transcribe(audio_path, language=source_lang)
            timing["transcribe_s"] = round(time.time() - t0, 1)
            await job.update(
                f"Transcribed {len(segments)} segments ({timing['transcribe_s']}s)"
            )

            # 4. Translate
            timing["translate_start"] = time.time()
            await job.update("Translating...")
            t0 = timing["translate_start"]
            segments = await translate_segments(
                segments, source_lang, req.target_language, progress_cb=progress
            )
            timing["translate_s"] = round(time.time() - t0, 1)
            job.metadata["segments_count"] = len(segments)
            await job.update(
                f"Translated {len(segments)} segments ({timing['translate_s']}s)"
            )

            # 5. Synthesize speech (voice cloning)
            timing["synthesis_start"] = time.time()
            await job.update("Synthesizing voice...")
            t0 = timing["synthesis_start"]
            reference_audio = Path(profile["reference_audio"])
            segments_dir = job_dir / "segments"
            segments = await voice.synthesize_all_segments(
                segments, req.target_language, reference_audio, segments_dir,
                progress_cb=progress
            )
            timing["synthesis_s"] = round(time.time() - t0, 1)

            # Collect per-segment synthesis timings
            seg_times = [s["synthesis_time_s"] for s in segments if s.get("synthesis_time_s")]
            if seg_times:
                timing["synthesis_avg_s"] = round(sum(seg_times) / len(seg_times), 2)
                timing["synthesis_min_s"] = round(min(seg_times), 2)
                timing["synthesis_max_s"] = round(max(seg_times), 2)
                timing["synthesis_per_segment_s"] = seg_times

            # Save segments metadata for potential video reconstruction
            segs_data = [
                {k: v for k, v in s.items() if k != "audio_path"}
                | {"audio_file": Path(s["audio_path"]).name if s.get("audio_path") else None}
                for s in segments
            ]
            (job_dir / "segments.json").write_text(
                json.dumps(segs_data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            # 6. Build audio track
            timing["render_audio_start"] = time.time()
            await job.update("Building audio track...")
            t0 = timing["render_audio_start"]
            merged_audio = temp_dir / "merged_audio.wav"
            await build_audio_track(
                segments,
                video_info["duration"],
                merged_audio,
                progress_cb=progress,
            )
            timing["render_audio_s"] = round(time.time() - t0, 1)

            # 7. Merge with video
            timing["render_start"] = time.time()
            await job.update("Rendering final video...")
            t0 = timing["render_start"]
            output_video = job_dir / "output.mp4"
            await merge_video_audio(video_path, merged_audio, output_video)
            timing["render_s"] = round(time.time() - t0, 1)

            timing["total_s"] = round(time.time() - t_start, 1)

            await job.finish({
                "video_url": f"/data/jobs/{job.id}/output.mp4",
                "title": video_info.get("title", "Translated video"),
                "duration": video_info.get("duration"),
                "source_language": source_lang,
                "target_language": req.target_language,
            })

        except Exception as e:
            tb = traceback.format_exc()
            timing["total_s"] = round(time.time() - t_start, 1)
            log.error("Job %s failed:\n%s", job.id, tb)
            await job.fail(f"{e}\n\n{tb}")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    asyncio.create_task(_run())
    return {"job_id": job.id}


# ─── Job status ────────────────────────────────────────────────────────────────

@app.get("/api/jobs")
def get_jobs():
    return list_jobs()

@app.get("/api/jobs/{job_id}")
def get_job_status(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job.to_dict()

@app.delete("/api/jobs/{job_id}")
def delete_job_endpoint(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    delete_job(job_id)
    job_dir = JOBS_DIR / job_id
    if job_dir.exists():
        shutil.rmtree(job_dir)
    return {"ok": True}

@app.websocket("/ws/jobs/{job_id}")
async def job_websocket(websocket: WebSocket, job_id: str):
    """Stream real-time progress updates for a job."""
    await websocket.accept()
    job = get_job(job_id)
    if not job:
        await websocket.send_json({"error": "Job not found"})
        await websocket.close()
        return

    await websocket.send_json(job.to_dict())

    try:
        last_progress = None
        while True:
            state = job.to_dict()
            if state["progress"] != last_progress or state["status"] in ("done", "error"):
                await websocket.send_json(state)
                last_progress = state["progress"]
                if state["status"] in ("done", "error"):
                    break
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        pass


@app.get("/")
def root():
    return {"message": "YoutubeTranslator API", "docs": "/docs", "app": "/app"}
