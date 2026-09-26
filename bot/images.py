# -*- coding: utf-8 -*-
"""Image sourcing, in order of preference:

  1. Pinterest API v5  - official, only if PINTEREST_TOKEN is set.
  2. Pexels API        - official, free, photos + videos.
  3. Pollinations      - free, no key, AI-generated.

Every source is optional; the first one that yields a usable file wins.
"""
import json
import os
import ssl
import urllib.parse
import urllib.request

from config import PEXELS_KEY, PINTEREST_TOKEN

_SSL = ssl.create_default_context()
UA = {"User-Agent": "Mozilla/5.0 (compatible; insta-webdesign/1.0)"}


class ImageError(RuntimeError):
    pass


def _get(url, headers, timeout=60):
    req = urllib.request.Request(url, headers=dict(UA, **headers))
    with urllib.request.urlopen(req, context=_SSL, timeout=timeout) as r:
        return r.read()


# --------------------------------------------------------------- pinterest --
def pinterest(query, limit=6):
    """Official Pinterest v5. Needs PINTEREST_TOKEN.

    NOTE: a *global* keyword search only exists as GET /search/partner/pins,
    which is beta and requires Pinterest's approval. Until that is granted we
    only search the authenticated user's own pins, which still works.
    """
    if not PINTEREST_TOKEN:
        return []
    out = []
    try:
        url = ("https://api.pinterest.com/v5/search/pins?query="
               + urllib.parse.quote(query) + f"&page_size={limit}")
        raw = _get(url, {"Authorization": "Bearer " + PINTEREST_TOKEN})
        for p in json.loads(raw).get("items") or []:
            media = p.get("media") or {}
            src = (media.get("images") or {}).get("1200x") or {}
            if src.get("url"):
                out.append(src["url"])
    except Exception:
        return []
    return out


# ------------------------------------------------------------------ pexels --
def pexels_photo(query, limit=8, orientation="landscape"):
    if not PEXELS_KEY:
        return []
    try:
        url = ("https://api.pexels.com/v1/search?query="
               + urllib.parse.quote(query)
               + f"&per_page={limit}&orientation={orientation}")
        data = json.loads(_get(url, {"Authorization": PEXELS_KEY}))
        return [p["src"]["original"] for p in data.get("photos", [])
                if (p.get("src") or {}).get("original")]
    except Exception:
        return []


def pexels_video(query, limit=5, min_height=1080):
    """Best matching portrait/landscape stock clip, as a direct mp4 URL."""
    if not PEXELS_KEY:
        return []
    try:
        url = ("https://api.pexels.com/videos/search?query="
               + urllib.parse.quote(query) + f"&per_page={limit}")
        data = json.loads(_get(url, {"Authorization": PEXELS_KEY}))
        out = []
        for v in data.get("videos", []):
            files = [f for f in (v.get("video_files") or []) if f.get("link")]
            files = [f for f in files if (f.get("height") or 0) >= min_height]
            if not files:
                continue
            best = max(files, key=lambda f: (f.get("width") or 0))
            out.append(best["link"])
        return out
    except Exception:
        return []


# ------------------------------------------------------------ pollinations --
def pollinations(query, width=1280, height=720, seed=None):
    """Free, keyless AI image generation."""
    url = ("https://image.pollinations.ai/prompt/"
           + urllib.parse.quote(query)
           + f"?width={width}&height={height}&nologo=true&model=flux"
           + (f"&seed={seed}" if seed is not None else ""))
    try:
        raw = _get(url, {}, timeout=240)
        if len(raw) < 4000:
            return None
        return raw
    except Exception:
        return None


# ----------------------------------------------------------------- generic --
def fetch_to(query, dest, *, portrait=False, prefer_ai=False, seed=None):
    """Save one usable image at `dest`. Returns the source name or raises."""
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    ext = os.path.splitext(dest)[1] or ".jpg"
    orient = "portrait" if portrait else "landscape"

    chains = []
    if prefer_ai:
        chains.append(("pollinations", lambda: [pollinations(
            query, 720 if portrait else 1280, 1280 if portrait else 720, seed)]))
    chains += [
        ("pinterest", lambda: pinterest(query)),
        ("pexels", lambda: pexels_photo(query, orientation=orient)),
        ("pollinations", lambda: [pollinations(
            query, 720 if portrait else 1280, 1280 if portrait else 720, seed)]),
    ]

    for name, fn in chains:
        for url in fn():
            try:
                raw = _get(url, {}, timeout=120)
            except Exception:
                continue
            if len(raw) < 8000:
                continue
            with open(dest, "wb") as fh:
                fh.write(raw)
            try:
                from PIL import Image
                with Image.open(dest) as im:
                    im.verify()
            except Exception:
                os.remove(dest)
                continue
            return name
    raise ImageError(f"no image found for query: {query!r}")
