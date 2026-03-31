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
from backend.services.transcribe import detect_language, transcribe, transcribe_stream
from backend.services.translate import translate_segments, translate_single, ensure_language_pair
from backend.services.render import build_audio_track, merge_video_audio
from backend.services.voice import _compute_speaker_latents, _run_inference, _merge_buffer, MAX_SEGMENT_DURATION
from backend.config import XTTS_LANGUAGES

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

            # 3. Language detection (fast: only first 30s, separate whisper pass)
            source_lang = req.source_language
            if not source_lang:
                await job.update("Detecting language...")
                source_lang = await detect_language(audio_path)
                await job.update(f"Detected language: {source_lang}")
            job.metadata["source_language"] = source_lang

            # Pre-install translation packages before pipeline starts
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, ensure_language_pair, source_lang, req.target_language)

            # 4-5-6. Pipeline: transcribe + translate + synthesize concurrently
            #
            # Stage 1 (transcribe) feeds → transcribe_q
            # Stage 2 (translate+buffer) consumes transcribe_q, feeds → synth_q
            # Stage 3 (synthesize) consumes synth_q
            # Speaker latents are computed in parallel with transcription.
            #
            transcribe_q: asyncio.Queue = asyncio.Queue()
            synth_q: asyncio.Queue = asyncio.Queue()

            reference_audio = Path(profile["reference_audio"])
            xtts_lang = XTTS_LANGUAGES.get(req.target_language, "en")
            segments_dir = job_dir / "segments"
            segments_dir.mkdir(parents=True, exist_ok=True)

            # Start computing speaker latents immediately (only needs reference audio)
            latents_task = asyncio.create_task(
                loop.run_in_executor(None, _compute_speaker_latents, reference_audio)
            )

            timing["transcribe_start"] = time.time()
            timing["translate_start"] = time.time()
            await job.update("Transcribing & translating...", JobStatus.RUNNING)

            async def stage_transcribe():
                try:
                    await transcribe_stream(audio_path, source_lang, transcribe_q)
                except Exception:
                    transcribe_q.put_nowait(None)  # unblock downstream on failure
                    raise
                finally:
                    timing["transcribe_s"] = round(time.time() - timing["transcribe_start"], 1)

            async def stage_translate():
                buffer: list[dict] = []
                seg_count = 0
                try:
                    while True:
                        seg = await transcribe_q.get()
                        if seg is None:
                            if buffer:
                                await synth_q.put(_merge_buffer(buffer))
                            await synth_q.put(None)
                            break
                        translated = await translate_single(seg["text"], source_lang, req.target_language)
                        seg["translated_text"] = translated
                        buffer.append(seg)
                        seg_count += 1
                        if buffer[-1]["end"] - buffer[0]["start"] >= MAX_SEGMENT_DURATION:
                            await synth_q.put(_merge_buffer(buffer))
                            buffer = []
                        progress(f"Transcribing & translating: {seg_count} segments")
                except Exception:
                    await synth_q.put(None)  # unblock synthesis on failure
                    raise
                finally:
                    timing["translate_s"] = round(time.time() - timing["translate_start"], 1)
                    job.metadata["segments_count"] = seg_count

            async def stage_synthesize():
                gpt_cond_latent, speaker_embedding = await latents_task
                timing["synthesis_start"] = time.time()
                await job.update("Synthesizing voice...")
                results: list[dict] = []
                chunk_n = 0
                seg_times: list[float] = []
                while True:
                    chunk = await synth_q.get()
                    if chunk is None:
                        break
                    text = (chunk.get("translated_text") or chunk.get("text") or "").strip()
                    if not text:
                        results.append({**chunk, "audio_path": None, "synthesis_time_s": 0.0})
                        continue
                    out_file = segments_dir / f"seg_{chunk_n:04d}.wav"
                    t_seg = time.time()
                    await loop.run_in_executor(
                        None, _run_inference, text, xtts_lang,
                        gpt_cond_latent, speaker_embedding, out_file
                    )
                    elapsed = round(time.time() - t_seg, 2)
                    seg_times.append(elapsed)
                    results.append({**chunk, "audio_path": str(out_file), "synthesis_time_s": elapsed})
                    chunk_n += 1
                    progress(f"Synthesizing: chunk {chunk_n} [{elapsed}s/chunk]")

                timing["synthesis_s"] = round(time.time() - timing["synthesis_start"], 1)
                if seg_times:
                    timing["synthesis_avg_s"] = round(sum(seg_times) / len(seg_times), 2)
                    timing["synthesis_min_s"] = round(min(seg_times), 2)
                    timing["synthesis_max_s"] = round(max(seg_times), 2)
                    timing["synthesis_per_segment_s"] = seg_times
                return results

            transcribe_task = asyncio.create_task(stage_transcribe())
            translate_task = asyncio.create_task(stage_translate())
            synth_task = asyncio.create_task(stage_synthesize())

            await asyncio.gather(transcribe_task, translate_task)
            segments = await synth_task

            await job.update(
                f"Pipeline done — {job.metadata.get('segments_count', '?')} segments"
                f" in {timing.get('synthesis_s', '?')}s synthesis"
            )

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
