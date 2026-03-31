# YoutubeTranslator

Translate any YouTube video into another language using your voice — fully local, no API keys required.

Downloads the video, transcribes the speech, translates the text, and synthesizes new audio in a cloned voice. The result is a dubbed video with the original speaker's voice in the target language.

---

## How it works

```
YouTube URL
    │
    ▼
yt-dlp          — download audio + video
    │
    ▼
faster-whisper  — transcribe speech to text (local Whisper)
    │
    ▼
argostranslate  — translate text offline (no API)
    │
    ▼
Coqui XTTS v2   — synthesize speech with voice cloning
    │
    ▼
ffmpeg          — merge new audio track into video
```

Everything runs locally. The first run downloads the XTTS v2 model (~1.8 GB) automatically.

---

## Features

- **Zero API keys** — Whisper, argostranslate, and XTTS v2 all run locally
- **Voice cloning** — clones the speaker's voice using a short reference audio clip
- **Voice profiles** — save reference clips and reuse them across jobs
- **Job queue** — jobs run in the background, survive server restarts, and are persisted to disk
- **Live progress** — real-time updates via WebSocket with per-phase timing
- **Web UI** — clean browser interface at `http://localhost:8000/app`

---

## Requirements

- Python 3.10+
- ffmpeg (in PATH, or installed via winget on Windows)
- ~4 GB disk space for models (downloaded on first use)
- GPU optional — runs on CPU, GPU speeds up Whisper and XTTS significantly

---

## Installation

```bash
# Windows — double-click or run:
install.bat

# Manual
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # Linux/macOS
pip install -r requirements.txt
```

---

## Usage

```bash
# Windows
start.bat

# Manual
venv\Scripts\activate
python run.py
```

Then open **http://localhost:8000/app** in your browser.

### Translate a video

1. Go to the **Translate** tab
2. Paste a YouTube URL and click **Fetch Info**
3. Select source and target language
4. Pick a voice profile (or create one first)
5. Click **Translate** — the job runs in the background

### Create a voice profile

1. Go to the **Voices** tab
2. Paste a YouTube URL and set a start time + duration (20–60s works best)
3. Give it a name and click **Create Profile**
4. The reference clip is saved and reused for synthesis

---

## Project structure

```
YoutubeTranslator/
├── backend/
│   ├── config.py          # paths, model settings, language list
│   ├── jobs.py            # job tracking + disk persistence
│   ├── main.py            # FastAPI routes
│   └── services/
│       ├── youtube.py     # yt-dlp wrapper
│       ├── transcribe.py  # faster-whisper
│       ├── translate.py   # argostranslate
│       ├── voice.py       # Coqui XTTS v2 voice cloning
│       └── render.py      # audio track assembly + ffmpeg merge
├── frontend/
│   ├── index.html
│   ├── app.js
│   └── styles.css
├── data/                  # generated at runtime (not versioned)
│   ├── jobs/              # job output + metadata per job ID
│   ├── voice_profiles/    # saved reference audio clips
│   └── temp/              # temporary files during processing
├── requirements.txt
├── install.bat
├── start.bat
└── run.py
```

---

## Supported languages

English, Dutch, German, French, Spanish, Italian, Portuguese, Polish, Russian, Japanese, Korean, Chinese

Translation pairs must be installed by argostranslate on first use.

---

## Known limitations / workarounds

- **torchaudio + torchcodec conflict** (torchaudio 2.11 on Windows): the `torchaudio.load()` function is patched at runtime to use `soundfile` as a fallback, avoiding missing FFmpeg DLL errors from torchcodec.
- **transformers pinned to 4.44.2**: TTS 0.22 requires `BeamSearchScorer` which was removed in transformers 4.45+.
- Synthesis is sequential per segment.

---

## Versions

### v2 — speed optimisations (~2× faster end-to-end)

The focus of v2 is **speed, not quality**. The pipeline produces the same result as v1 but in roughly half the time, measured on the same video. Output quality is comparable; the longer synthesis chunks may even improve prosody slightly, but that is a side effect rather than a goal.

- **Speaker embedding caching**: XTTS v2 conditioning latents computed once per job and reused for every segment, eliminating redundant voice analysis on every TTS call (~20-40% faster synthesis)
- **Segment merging**: adjacent Whisper segments merged into chunks up to 15s before synthesis, drastically reducing the number of TTS calls from ~170 to ~40 for a 17-min video (~30-50% faster synthesis)
- **Smaller Whisper model**: `medium` → `small` for faster transcription with minimal quality loss on European languages

### v1 — initial release

- Full pipeline: download → transcribe → translate → voice clone → render
- Voice profiles with reference audio
- Job persistence across server restarts
- Live progress via WebSocket
- Per-phase timing in job detail panel
- Web UI with Translate, Voices, and Jobs tabs

---

## Roadmap

- Pipeline overlapping (transcribe while downloading, translate while transcribing)
- Chrome extension integration
