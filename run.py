"""
Start the YoutubeTranslator backend with clean terminal output.
Collapses repeated poll/download lines into a single updating line.
Usage: python run.py
"""
import re
import subprocess
import sys

POLL_RE    = re.compile(r'GET /api/jobs/[a-f0-9-]+')
DL_RE      = re.compile(r'\[download\]\s+([\d.]+)%.*?ETA\s+(\S+)')
DL_DONE_RE = re.compile(r'\[download\]\s+100%')


def make_bar(pct: float, width: int = 20) -> str:
    filled = int(width * pct / 100)
    return "█" * filled + "░" * (width - filled)


def run():
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn",
         "backend.main:app",
         "--host", "0.0.0.0",
         "--port", "8000",
         "--reload"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    poll_count   = 0
    in_poll      = False
    in_download  = False

    def end_inline():
        """Move to next line after an inline-updated line."""
        sys.stdout.write("\n")
        sys.stdout.flush()

    try:
        for line in proc.stdout:
            line = line.rstrip()

            # ── Polling requests ──────────────────────────────────────────
            if POLL_RE.search(line):
                poll_count += 1
                if in_download:
                    end_inline()
                    in_download = False
                msg = f"  polling ({poll_count}x)"
                sys.stdout.write(f"\r\033[2K{msg}")
                sys.stdout.flush()
                in_poll = True
                continue

            # ── yt-dlp download progress ──────────────────────────────────
            m = DL_RE.search(line)
            if m:
                pct = float(m.group(1))
                eta = m.group(2)
                if in_poll:
                    end_inline()
                    in_poll = False
                    poll_count = 0
                bar = make_bar(pct)
                msg = f"  download [{bar}] {pct:5.1f}%  ETA {eta}"
                sys.stdout.write(f"\r\033[2K{msg}")
                sys.stdout.flush()
                in_download = True
                continue

            if DL_DONE_RE.search(line):
                if in_download:
                    end_inline()
                    in_download = False
                sys.stdout.write("  download [████████████████████] 100%\n")
                sys.stdout.flush()
                continue

            # ── Any other line ────────────────────────────────────────────
            if in_poll or in_download:
                end_inline()
                in_poll     = False
                in_download = False
                poll_count  = 0

            sys.stdout.write(line + "\n")
            sys.stdout.flush()

    except KeyboardInterrupt:
        proc.terminate()


if __name__ == "__main__":
    run()
