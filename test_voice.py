"""
Quick test for voice synthesis without going through transcription.
Usage: python test_voice.py [profile_id] [text] [language]

Examples:
  python test_voice.py                          # list profiles, use defaults
  python test_voice.py abc123 "Hello world" en
  python test_voice.py abc123 "Bonjour le monde" fr
"""
import sys
import os
from pathlib import Path

# Make sure backend config runs (sets up ffmpeg PATH etc.)
sys.path.insert(0, str(Path(__file__).parent))
from backend.config import PROFILES_DIR

def list_profiles():
    profiles = []
    for d in PROFILES_DIR.iterdir():
        if d.is_dir() and (d / "metadata.json").exists():
            import json
            meta = json.loads((d / "metadata.json").read_text())
            profiles.append((d.name, meta.get("name", "?"), d / "reference.wav"))
    return profiles

profiles = list_profiles()
if not profiles:
    print("No voice profiles found. Create one first via the web UI.")
    sys.exit(1)

print("Available profiles:")
for pid, name, ref in profiles:
    print(f"  {pid[:8]}...  {name}  ({ref})")

# Args
profile_id = sys.argv[1] if len(sys.argv) > 1 else profiles[0][0]
text       = sys.argv[2] if len(sys.argv) > 2 else "This is a test of the voice cloning system."
language   = sys.argv[3] if len(sys.argv) > 3 else "en"

# Find matching profile
match = next((p for p in profiles if p[0].startswith(profile_id)), None)
if not match:
    print(f"Profile '{profile_id}' not found.")
    sys.exit(1)

pid, name, reference_audio = match
print(f"\nUsing profile: {name} ({pid})")
print(f"Text:          {text}")
print(f"Language:      {language}")

output_path = Path("test_output.wav")

print("\nLoading XTTS v2 model (may take a moment)...")
os.environ["COQUI_TOS_AGREED"] = "1"
from TTS.api import TTS
tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2")

from backend.config import XTTS_LANGUAGES
xtts_lang = XTTS_LANGUAGES.get(language, "en")
print(f"Synthesizing ({xtts_lang})...")

tts.tts_to_file(
    text=text,
    speaker_wav=str(reference_audio),
    language=xtts_lang,
    file_path=str(output_path),
)

print(f"\nDone! Output saved to: {output_path.absolute()}")
