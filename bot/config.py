# -*- coding: utf-8 -*-
"""Central configuration.

Every secret comes from the environment (GitHub Actions secrets) - nothing
sensitive is ever committed to the repository.
"""
import os
import shutil

_HERE = os.path.dirname(os.path.abspath(__file__))


def _flag(name, default="0"):
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


def _int(name, default):
    try:
        return int(str(os.environ.get(name, default)).strip())
    except ValueError:
        return default


def _gemini_key():
    k = os.environ.get("GEMINI_KEY", "").strip()
    if k:
        return k
    p = os.path.join(_HERE, ".key")
    if os.path.exists(p):
        return open(p, encoding="utf-8").read().strip()
    return ""


GEMINI_KEY = _gemini_key()
PEXELS_KEY = os.environ.get("PEXELS_KEY", "").strip()

# Optional integrations - the pipeline degrades gracefully when absent.
PINTEREST_TOKEN = os.environ.get("PINTEREST_TOKEN", "").strip()
IG_ACCESS_TOKEN = os.environ.get("IG_ACCESS_TOKEN", "").strip()
IG_USER_ID = os.environ.get("IG_USER_ID", "").strip()

# Public base URL used when a third party must fetch our media (Instagram
# Graph API refuses localhost/private URLs). Example:
#   https://fyosamu.github.io/insta-webdesign
PUBLIC_BASE = os.environ.get("PUBLIC_BASE", "").rstrip("/")

DAILY_POSTS = _int("DAILY_POSTS", 3)
DAILY_REELS = _int("DAILY_REELS", 3)
REEL_SECONDS = _int("REEL_SECONDS", 20)

# Safety gate. Generation always runs; publishing only happens when APPROVED=1
# and a token is present. DRY_RUN=1 prints what would be posted instead.
DRY_RUN = _flag("DRY_RUN", "1")
APPROVED = _flag("APPROVED", "0")

ROOT = os.path.dirname(_HERE)
OUT = os.environ.get("OUT_DIR") or os.path.join(ROOT, "out")

NICHE = os.environ.get(
    "NICHE",
    "Web design for beginners: why every business needs a website, "
    "and why a website is the best place to sell your products.",
)

_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\segoeuib.ttf",
    r"C:\Windows\Fonts\arialbd.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
]

_REGULAR_CANDIDATES = [
    r"C:\Windows\Fonts\segoeui.ttf",
    r"C:\Windows\Fonts\arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
]


def font(bold=True):
    for p in (_FONT_CANDIDATES if bold else _REGULAR_CANDIDATES):
        if os.path.exists(p):
            return p
    return None


FFMPEG = shutil.which("ffmpeg") or ""
FFPROBE = shutil.which("ffprobe") or ""


def require_ffmpeg():
    if not FFMPEG:
        raise SystemExit("ffmpeg not found on PATH (apt install ffmpeg / winget install ffmpeg)")
    return FFMPEG


def probe_has_audio(path):
    if not FFPROBE:
        return False
    try:
        import subprocess
        out = subprocess.run(
            [FFPROBE, "-v", "error", "-select_streams", "a", "-show_entries",
             "stream=index", "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=60)
        return bool(out.stdout.strip())
    except Exception:
        return False
