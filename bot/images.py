# -*- coding: utf-8 -*-
"""Image sourcing, in order of preference:

  1. Pinterest API v5  - official, only if PINTEREST_TOKEN is set.
  2. Pexels API        - official, free, photos + videos.
  3. Pollinations      - free, no key, AI-generated.

Every source is optional; the first one that yields a usable file wins.
"""
import http.client
import json
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

from config import PEXELS_KEY, PINTEREST_TOKEN

_SSL = ssl.create_default_context()
UA = {"User-Agent": "Mozilla/5.0 (compatible; insta-webdesign/1.0)"}

# --- transport retry ---------------------------------------------------
# A stock host that refuses a connection once, or drops a 29MB clip halfway
# through, is routine. Treating that as "there is no footage for this
# query" silently costs a whole reel, and the daily schedule never comes
# back for the one it skipped - so the failure only surfaces as a hole in
# the day's output. The transport therefore makes a bounded second and
# third attempt before any caller gets to conclude that nothing matched.
RETRY_ATTEMPTS = 3
RETRY_DELAY = 1.5      # seconds, multiplied by the attempt number


class ImageError(RuntimeError):
    pass


def _transient(exc):
    """Is another attempt worth making?

    Only transport trouble. A 404 is a settled answer, and HTTPError is a
    subclass of URLError, so the status check has to come first or every
    bad request would be retried into the ground.
    """
    if isinstance(exc, http.client.IncompleteRead):
        return True
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code in (408, 425, 429, 500, 502, 503, 504)
    return isinstance(exc, (urllib.error.URLError, TimeoutError,
                            ConnectionError, OSError))


def _get(url, headers, timeout=60, attempts=RETRY_ATTEMPTS):
    req = urllib.request.Request(url, headers=dict(UA, **headers))
    last = None
    for attempt in range(max(1, attempts)):
        try:
            with urllib.request.urlopen(req, context=_SSL,
                                        timeout=timeout) as r:
                return r.read()
        except Exception as exc:
            last = exc
            if attempt + 1 >= attempts or not _transient(exc):
                raise
            time.sleep(RETRY_DELAY * (attempt + 1))
    raise last


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

    offered = 0            # candidates the sources actually put forward
    for name, fn in chains:
        try:
            urls = fn() or []
        except Exception:
            urls = []      # one source being down must not end the chain
        for url in urls:
            if not url:
                continue
            offered += 1
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
    # Two different endings that look identical from the outside. When no
    # source offered anything the network or a key is at fault and retrying
    # elsewhere will not help; when candidates were offered and none held
    # up, the query is the problem. Saying which is the whole difference
    # between debugging a connection and rewriting a prompt.
    if not offered:
        raise ImageError(f"no source answered for query: {query!r}"
                         " - network down or key missing")
    raise ImageError(f"no image found for query: {query!r}")
