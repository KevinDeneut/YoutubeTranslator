import os
import shutil
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent

# Auto-detect ffmpeg: check PATH first, then common winget install location
def _find_ffmpeg() -> str | None:
    if shutil.which("ffmpeg"):
        return shutil.which("ffmpeg")
    winget_path = Path.home() / "AppData/Local/Microsoft/WinGet/Packages"
    for d in winget_path.glob("Gyan.FFmpeg*/*/bin/ffmpeg.exe"):
        return str(d)
    return None

FFMPEG_PATH = _find_ffmpeg()
if FFMPEG_PATH:
    # Add ffmpeg's bin dir to PATH so all tools (yt-dlp, pydub, ffmpeg-python) find it
    ffmpeg_bin = str(Path(FFMPEG_PATH).parent)
    os.environ["PATH"] = ffmpeg_bin + os.pathsep + os.environ.get("PATH", "")
DATA_DIR = BASE_DIR / "data"
PROFILES_DIR = DATA_DIR / "voice_profiles"
JOBS_DIR = DATA_DIR / "jobs"
TEMP_DIR = DATA_DIR / "temp"

for d in [PROFILES_DIR, JOBS_DIR, TEMP_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# Whisper model size: tiny, base, small, medium, large-v3
# Larger = more accurate, slower
WHISPER_MODEL = "medium"

# Whisper compute type: int8 (fast, less VRAM), float16 (better, needs GPU)
WHISPER_COMPUTE_TYPE = "int8"

# XTTS v2 model (downloaded automatically on first use, ~1.8GB)
XTTS_MODEL = "tts_models/multilingual/multi-dataset/xtts_v2"

# Languages supported by argos-translate (install pairs on demand)
# Format: "en", "nl", "de", "fr", "es", "it", "pt", "pl", "ru", "ja", "ko", "zh"
SUPPORTED_LANGUAGES = {
    "en": "English",
    "nl": "Nederlands",
    "de": "Deutsch",
    "fr": "French",
    "es": "Spanish",
    "it": "Italian",
    "pt": "Portuguese",
    "pl": "Polish",
    "ru": "Russian",
    "ja": "Japanese",
    "ko": "Korean",
    "zh": "Chinese",
}

APP_VERSION = "v1"

# XTTS supported languages (subset)
XTTS_LANGUAGES = {
    "en": "en", "nl": "nl", "de": "de", "fr": "fr", "es": "es",
    "it": "it", "pt": "pt", "pl": "pl", "ru": "ru", "ja": "ja",
    "ko": "ko", "zh-cn": "zh-cn",
}
